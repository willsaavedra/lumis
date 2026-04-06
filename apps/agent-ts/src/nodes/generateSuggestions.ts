import { v4 as uuidv4 } from 'uuid';
import type { AgentStateType } from '../graph/state.js';
import type { Suggestion, Finding } from '../graph/types.js';
import { chatComplete } from '../llm/client.js';
import { getModel, estimateTokens, computeMaxOutputTokens } from '../llm/config.js';
import { publishProgress } from '../utils/progress.js';
import { logger } from '../utils/logger.js';

const MAX_SUGGESTIONS = 20;

export async function generateSuggestionsNode(
  state: AgentStateType,
): Promise<Partial<AgentStateType>> {
  const { request, findings, classifiedFiles } = state;
  const log = logger.child({ jobId: request.jobId, node: 'generateSuggestions' });
  const start = Date.now();
  log.info({ event: 'node_started', node: 'generateSuggestions' });

  await publishProgress(request.jobId, 'suggestions', 95, 'Generating code suggestions...');

  const actionableFindings = findings
    .filter((f) => f.filePath && f.severity !== 'info' && f.confidence >= 0.5)
    .slice(0, MAX_SUGGESTIONS);

  const suggestions: Suggestion[] = [];

  for (const finding of actionableFindings) {
    const file = classifiedFiles.find((f) => f.path === finding.filePath);
    if (!file?.content) {
      if (finding.suggestion) {
        suggestions.push({
          findingId: finding.id ?? uuidv4(),
          filePath: finding.filePath!,
          codeBefore: finding.codeBefore ?? '',
          codeAfter: finding.codeAfter ?? finding.suggestion,
          explanation: finding.description,
        });
      }
      continue;
    }

    const codeSnippet = extractSnippet(file.content, finding.lineStart, finding.lineEnd);

    const sysPrompt = `You are a code suggestion generator. Given a finding and the relevant code, generate a specific code fix.
Respond with JSON: { "code_before": "...", "code_after": "...", "explanation": "..." }
Keep suggestions minimal and focused. Only change what's necessary to address the finding.`;
    const usrPrompt = `Finding: ${finding.title}
Description: ${finding.description}
File: ${finding.filePath}
${finding.suggestion ? `Suggested approach: ${finding.suggestion}` : ''}

Current code:
\`\`\`
${codeSnippet}
\`\`\``;

    const sugModel = getModel(request.llmProvider, 'triage');
    const sugInputTokens = estimateTokens(sysPrompt) + estimateTokens(usrPrompt);
    const sugMaxTokens = computeMaxOutputTokens(sugModel, sugInputTokens, 1024);

    try {
      const resp = await chatComplete({
        system: sysPrompt,
        user: usrPrompt,
        provider: request.llmProvider,
        model: sugModel,
        maxTokens: sugMaxTokens,
        temperature: 0.2,
      });

      try {
        const jsonMatch = resp.text.match(/\{[\s\S]*\}/);
        if (jsonMatch) {
          const parsed = JSON.parse(jsonMatch[0]);
          suggestions.push({
            findingId: finding.id ?? uuidv4(),
            filePath: finding.filePath!,
            codeBefore: parsed.code_before ?? codeSnippet,
            codeAfter: parsed.code_after ?? '',
            explanation: parsed.explanation ?? finding.description,
          });

          finding.codeBefore = parsed.code_before ?? codeSnippet;
          finding.codeAfter = parsed.code_after ?? '';
        }
      } catch {
        log.warn({ event: 'suggestion_parse_failed', findingTitle: finding.title });
      }
    } catch (err) {
      log.warn({ event: 'suggestion_generation_failed', findingTitle: finding.title, error: (err as Error).message });
    }
  }

  const durationMs = Date.now() - start;
  log.info({ event: 'node_completed', node: 'generateSuggestions', durationMs, suggestionsCount: suggestions.length });

  return { suggestions, stage: 'suggestions', progressPct: 98 };
}

function extractSnippet(content: string, lineStart?: number, lineEnd?: number): string {
  const lines = content.split('\n');
  const start = Math.max(0, (lineStart ?? 1) - 3);
  const end = Math.min(lines.length, (lineEnd ?? lineStart ?? lines.length) + 3);
  return lines.slice(start, end).join('\n');
}
