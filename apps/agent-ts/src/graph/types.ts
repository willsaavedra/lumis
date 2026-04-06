export type AnalysisType = 'quick' | 'full' | 'repository' | 'context';
export type LlmProvider = 'anthropic' | 'cerebra_ai';
export type Severity = 'critical' | 'warning' | 'info';
export type ScmType = 'github' | 'gitlab' | 'bitbucket';
export type PromptMode = 'fast' | 'standard' | 'deep' | 'verify';

export type Pillar =
  | 'metrics'
  | 'logs'
  | 'traces'
  | 'iac'
  | 'pipeline'
  | 'security'
  | 'efficiency'
  | 'compliance';

export type Dimension =
  | 'cost'
  | 'snr'
  | 'pipeline'
  | 'compliance'
  | 'coverage'
  | 'security'
  | 'performance'
  | 'quality';

export interface RepoContext {
  repoType: string;
  /** API/worker pode enviar string ou lista (Postgres `language` é ARRAY). */
  language: string | string[] | null;
  observabilityBackend?: string;
  contextSummary?: string;
}

export interface AnalysisRequest {
  jobId: string;
  tenantId: string;
  repoId: string;
  repoFullName: string;
  cloneUrl: string;
  ref: string;
  installationId?: number;
  scmType: ScmType;
  changedFiles?: string[];
  analysisType: AnalysisType;
  llmProvider: LlmProvider;
  repoContext: RepoContext;
  previousFindings?: Finding[];
  ragContext?: string;
}

export interface Finding {
  id?: string;
  pillar: Pillar;
  severity: Severity;
  dimension: Dimension;
  title: string;
  description: string;
  filePath?: string;
  lineStart?: number;
  lineEnd?: number;
  suggestion?: string;
  codeBefore?: string;
  codeAfter?: string;
  estimatedMonthlyCostImpact: number;
  isNew?: boolean;
  crossrunStatus?: 'new' | 'persisting' | 'resolved';
  reasoning?: string;

  sourceAgent: string;
  crossDomainHints?: string[];
  enrichedBy?: string[];
  originalSourceAgent?: string;
  confidence: number;
  promptMode?: PromptMode;
  verified?: boolean;
  reasoningExcerpt?: string;
}

export interface CrossDomainReferral {
  findingIndex: number;
  targetDomain: string;
  reason: string;
  contextSnippet: string;
}

export interface EnrichmentResult {
  findingIndex: number;
  action: 'enrich' | 'suppress' | 'noop';
  severity?: Severity;
  enrichedDescription?: string;
  suggestion?: string;
  reasoning?: string;
}

export interface Scores {
  global: number;
  metrics: number;
  logs: number;
  traces: number;
  cost: number;
  snr: number;
  pipeline: number;
  compliance: number;
  security?: number;
  efficiency?: number;
}

export interface Suggestion {
  findingId: string;
  filePath: string;
  codeBefore: string;
  codeAfter: string;
  explanation: string;
}

export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  costUsd: number;
  llmCalls: number;
}

export interface AgentStats {
  agentName: string;
  findingsCount: number;
  tokensUsed: number;
  durationMs: number;
  promptMode: PromptMode;
}

export interface AnalysisResponse {
  findings: Finding[];
  scores: Scores;
  suggestions: Suggestion[];
  tokenUsage: TokenUsage;
  agentBreakdown: Record<string, AgentStats>;
  crossrunSummary?: CrossrunSummary;
  contextSummary?: string;
}

export interface CrossrunSummary {
  newCount: number;
  persistingCount: number;
  resolvedCount: number;
  resolvedFindings: string[];
  previousJobId?: string;
}

export interface ClassifiedFile {
  path: string;
  language: string | null;
  relevanceScore: number;
  content: string | null;
  detectedArtifacts?: string[];
}

export interface CallGraphNode {
  name: string;
  filePath: string;
  line: number;
  nodeType: 'handler' | 'db_call' | 'http_client' | 'cache' | 'queue' | 'utility';
  callers: string[];
  callees: string[];
}

export interface CallGraph {
  nodes: Record<string, CallGraphNode>;
  entryPoints: string[];
  ioNodes: string[];
  errorPaths: string[];
}

export interface AgentContext {
  files: ClassifiedFile[];
  ragContext: string | null;
  /**
   * Texto agregado dos micro-agents ativos: prioridades de observabilidade por linguagem/stack
   * (o domínio D-observability usa para focar métricas/logs/traces relevantes ao repo).
   */
  microAgentObservabilityHints: string | null;
  llmProvider: LlmProvider;
  analysisType: AnalysisType;
  callGraph: CallGraph | null;
  repoContext: RepoContext;
  ddCoverage: Record<string, unknown> | null;
}
