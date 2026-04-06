import { Annotation } from '@langchain/langgraph';
import type {
  AnalysisRequest,
  ClassifiedFile,
  CrossDomainReferral,
  Finding,
  Scores,
  Suggestion,
  TokenUsage,
  AgentStats,
  CallGraph,
  CrossrunSummary,
} from './types.js';

function sumTokens(a: TokenUsage, b: TokenUsage): TokenUsage {
  return {
    promptTokens: a.promptTokens + b.promptTokens,
    completionTokens: a.completionTokens + b.completionTokens,
    totalTokens: a.totalTokens + b.totalTokens,
    costUsd: a.costUsd + b.costUsd,
    llmCalls: a.llmCalls + b.llmCalls,
  };
}

export const AgentState = Annotation.Root({
  request: Annotation<AnalysisRequest>,
  repoPath: Annotation<string | null>({ default: () => null, reducer: (_c, u) => u }),

  classifiedFiles: Annotation<ClassifiedFile[]>({
    default: () => [],
    reducer: (_c, u) => u,
  }),
  callGraph: Annotation<CallGraph | null>({ default: () => null, reducer: (_c, u) => u }),
  ddCoverage: Annotation<Record<string, unknown> | null>({
    default: () => null,
    reducer: (_c, u) => u,
  }),
  ragContext: Annotation<string | null>({ default: () => null, reducer: (_c, u) => u }),
  /** Agregado dos micro-agents: focos por linguagem para o D-observability. */
  microAgentObservabilityHints: Annotation<string | null>({
    default: () => null,
    reducer: (_c, u) => u,
  }),

  detectedLanguages: Annotation<string[]>({
    default: () => [],
    reducer: (_c, u) => u,
  }),
  detectedArtifacts: Annotation<string[]>({
    default: () => [],
    reducer: (_c, u) => u,
  }),
  activeAgents: Annotation<string[]>({
    default: () => [],
    reducer: (_c, u) => u,
  }),

  findings: Annotation<Finding[]>({
    default: () => [],
    reducer: (cur, upd) => [...cur, ...upd],
  }),
  referrals: Annotation<CrossDomainReferral[]>({
    default: () => [],
    reducer: (cur, upd) => [...cur, ...upd],
  }),
  scores: Annotation<Scores | null>({ default: () => null, reducer: (_c, u) => u }),
  suggestions: Annotation<Suggestion[]>({
    default: () => [],
    reducer: (_c, u) => u,
  }),
  tokenUsage: Annotation<TokenUsage>({
    default: () => ({ promptTokens: 0, completionTokens: 0, totalTokens: 0, costUsd: 0, llmCalls: 0 }),
    reducer: (cur, upd) => sumTokens(cur, upd),
  }),
  agentBreakdown: Annotation<Record<string, AgentStats>>({
    default: () => ({}),
    reducer: (cur, upd) => ({ ...cur, ...upd }),
  }),

  previousJobId: Annotation<string | null>({ default: () => null, reducer: (_c, u) => u }),
  crossrunSummary: Annotation<CrossrunSummary | null>({
    default: () => null,
    reducer: (_c, u) => u,
  }),

  stage: Annotation<string>({ default: () => 'pending', reducer: (_c, u) => u }),
  progressPct: Annotation<number>({ default: () => 0, reducer: (_c, u) => u }),
  error: Annotation<string | null>({ default: () => null, reducer: (_c, u) => u }),

  contextSummary: Annotation<string | null>({ default: () => null, reducer: (_c, u) => u }),
  suppressed: Annotation<Array<{ filePath: string; line: number }>>({
    default: () => [],
    reducer: (cur, upd) => [...cur, ...upd],
  }),
});

export type AgentStateType = typeof AgentState.State;
