import { readdir, readFile, stat } from 'node:fs/promises';
import { join, extname, basename } from 'node:path';
import type { AgentStateType } from '../graph/state.js';
import type { ClassifiedFile } from '../graph/types.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

const LANG_MAP: Record<string, string> = {
  '.ts': 'typescript', '.tsx': 'typescript', '.js': 'javascript', '.jsx': 'javascript',
  '.go': 'go', '.py': 'python', '.rs': 'rust',
  '.java': 'java', '.kt': 'kotlin', '.scala': 'scala',
  '.c': 'c', '.cpp': 'cpp', '.cc': 'cpp', '.h': 'c', '.hpp': 'cpp',
  '.rb': 'ruby', '.php': 'php', '.cs': 'csharp',
  '.tf': 'terraform', '.hcl': 'terraform',
  '.yaml': 'yaml', '.yml': 'yaml',
  '.sql': 'sql', '.proto': 'protobuf',
  '.md': 'markdown', '.json': 'json', '.toml': 'toml',
};

const ARTIFACT_PATTERNS: Record<string, RegExp[]> = {
  docker: [/Dockerfile/i, /docker-compose/i, /\.dockerignore/],
  kubernetes: [/k8s\//i, /\.ya?ml$/, /deployment/, /service\.ya?ml/],
  helm: [/Chart\.ya?ml/, /values\.ya?ml/, /templates\//],
  terraform: [/\.tf$/, /\.tfvars$/],
  ci: [/\.github\/workflows/, /\.gitlab-ci/, /Jenkinsfile/, /\.circleci/],
  openapi: [/openapi/, /swagger/],
  protobuf: [/\.proto$/],
  database: [/migrations?\//i, /\.sql$/],
  testing: [/_test\.\w+$/, /\.spec\.\w+$/, /\.test\.\w+$/, /__tests__\//],
  react: [/\.tsx$/, /\.jsx$/, /next\.config/, /vite\.config/],
};

const IGNORE_DIRS = new Set([
  'node_modules', '.git', 'vendor', 'dist', 'build', '.next',
  '__pycache__', '.venv', 'venv', '.mypy_cache', 'target',
  '.idea', '.vscode', 'coverage', '.turbo',
]);

const MAX_FILE_SIZE = 100_000;
const MAX_FILES = 500;

async function walkDir(dir: string, base: string): Promise<string[]> {
  const results: string[] = [];
  const entries = await readdir(dir, { withFileTypes: true });

  for (const entry of entries) {
    if (IGNORE_DIRS.has(entry.name)) continue;
    if (entry.name.startsWith('.') && entry.name !== '.github') continue;

    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      const sub = await walkDir(fullPath, base);
      results.push(...sub);
    } else {
      const rel = fullPath.slice(base.length + 1);
      results.push(rel);
    }
    if (results.length >= MAX_FILES) break;
  }

  return results;
}

function detectLanguage(filePath: string): string | null {
  const ext = extname(filePath).toLowerCase();
  return LANG_MAP[ext] ?? null;
}

function detectArtifacts(filePath: string): string[] {
  const artifacts: string[] = [];
  for (const [artifact, patterns] of Object.entries(ARTIFACT_PATTERNS)) {
    for (const pattern of patterns) {
      if (pattern.test(filePath) || pattern.test(basename(filePath))) {
        artifacts.push(artifact);
        break;
      }
    }
  }
  return artifacts;
}

function computeRelevance(filePath: string, lang: string | null, changedFiles?: string[]): number {
  if (changedFiles?.includes(filePath)) return 2;

  const lower = filePath.toLowerCase();
  if (lower.includes('test') || lower.includes('spec') || lower.includes('mock')) return 0;
  if (lower.includes('vendor/') || lower.includes('generated')) return 0;
  if (!lang) return 0;
  if (lower.startsWith('src/') || lower.startsWith('app/') || lower.startsWith('lib/') || lower.startsWith('cmd/') || lower.startsWith('internal/') || lower.startsWith('pkg/')) return 2;
  return 1;
}

export async function preTriageNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request, repoPath } = state;
  const log = logger.child({ jobId: request.jobId, node: 'preTriage' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'preTriage' });

  await publishProgress(request.jobId, 'triage', 15, 'Classifying files...');

  if (!repoPath) {
    log.error({ event: 'node_failed', error: 'repoPath is null' });
    return { error: 'repoPath is null' };
  }

  const allPaths = await walkDir(repoPath, repoPath);
  const languageSet = new Set<string>();
  const artifactSet = new Set<string>();
  const classifiedFiles: ClassifiedFile[] = [];

  for (const relPath of allPaths.slice(0, MAX_FILES)) {
    const lang = detectLanguage(relPath);
    const artifacts = detectArtifacts(relPath);
    const relevance = computeRelevance(relPath, lang, request.changedFiles);

    if (lang) languageSet.add(lang);
    artifacts.forEach((a) => artifactSet.add(a));

    let content: string | null = null;
    if (relevance >= 1) {
      const fullPath = join(repoPath, relPath);
      try {
        const stats = await stat(fullPath);
        if (stats.size <= MAX_FILE_SIZE) {
          content = await readFile(fullPath, 'utf-8');
        }
      } catch {
        // skip unreadable files
      }
    }

    classifiedFiles.push({
      path: relPath,
      language: lang,
      relevanceScore: relevance,
      content,
      detectedArtifacts: artifacts.length > 0 ? artifacts : undefined,
    });
  }

  const suppressed = classifiedFiles
    .filter((f) => f.content?.includes('lumis-ignore'))
    .map((f) => ({ filePath: f.path, line: 0 }));

  const durationMs = Date.now() - start;
  log.info({
    event: 'node_completed',
    node: 'preTriage',
    durationMs,
    totalFiles: classifiedFiles.length,
    relevantFiles: classifiedFiles.filter((f) => f.relevanceScore >= 1).length,
    languages: [...languageSet],
    artifacts: [...artifactSet],
  });

  return {
    classifiedFiles,
    detectedLanguages: [...languageSet],
    detectedArtifacts: [...artifactSet],
    suppressed,
    stage: 'triage',
    progressPct: 20,
  };
}
