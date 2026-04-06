import type { PromptMode, AnalysisType } from '../graph/types.js';

export function selectPromptMode(analysisType: AnalysisType, fileCount: number): PromptMode {
  if (analysisType === 'quick' && fileCount <= 5) return 'fast';
  if (analysisType === 'quick') return 'standard';
  if (analysisType === 'repository') return 'deep';
  if (fileCount > 50) return 'deep';
  return 'standard';
}

export const REASONING_FRAMEWORK = `
When analyzing each code section, apply this Q1-Q4 reasoning framework:

Q1: Is there existing observability instrumentation? (spans, metrics, structured logs)
Q2: What critical paths lack coverage? (error handling, external calls, state transitions)
Q3: Are there anti-patterns? (high-cardinality metrics, unstructured logs, missing context propagation)
Q4: What is the production impact of each gap? (blind spots in debugging, missing alerts, cost waste)

For each finding, include your reasoning in the "reasoning" field showing which Q(s) triggered it.
Only emit findings with confidence >= 0.5. When uncertain, prefer specificity over breadth.
`.trim();

export const NEGATIVE_EXAMPLES = `
DO NOT emit findings for:
- Boilerplate/generated code (protobuf stubs, mocks, test fixtures)
- Already well-instrumented code (has spans + metrics + structured logs)
- Configuration files unless they directly impact observability
- Cosmetic issues (formatting, naming that doesn't affect observability)
`.trim();
