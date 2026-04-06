import { DomainAgent } from '../DomainAgent.js';
import type { ClassifiedFile, AgentContext, CrossDomainReferral, PromptMode, Pillar } from '../../graph/types.js';
import type { AgentStateType } from '../../graph/state.js';

export class DPerformance extends DomainAgent {
  readonly name = 'D-performance';
  readonly pillar: Pillar = 'efficiency';
  readonly defaultMode: PromptMode = 'deep';

  accepts(file: ClassifiedFile): boolean {
    if (!file.content) return false;
    const lower = file.content.toLowerCase();
    const p = file.path.toLowerCase();
    return (
      lower.includes('pool') ||
      lower.includes('cache') ||
      lower.includes('concurrent') ||
      lower.includes('goroutine') ||
      lower.includes('async') ||
      lower.includes('await') ||
      lower.includes('promise') ||
      lower.includes('mutex') ||
      lower.includes('channel') ||
      lower.includes('pagination') ||
      lower.includes('batch') ||
      lower.includes('buffer') ||
      lower.includes('stream') ||
      lower.includes('queue') ||
      p.includes('handler') ||
      p.includes('service') ||
      p.includes('controller') ||
      p.includes('route') ||
      file.relevanceScore >= 2
    );
  }

  isRelevant(_state: AgentStateType): boolean {
    return true;
  }

  getSystemPrompt(context: AgentContext): string {
    return `You are a performance specialist reviewing code for performance issues and bottlenecks.

Focus areas:
- N+1 query patterns in any language/framework
- Memory leaks (event listeners not removed, closures holding references)
- Blocking I/O on hot paths (sync file reads, blocking network calls)
- Unbounded caches or growing data structures
- Missing pagination causing full table scans
- Concurrency anti-patterns (lock contention, deadlock risks)
- Inefficient serialization/deserialization
- Large payload sizes without compression
- Missing connection pooling for external services
- CPU-intensive operations on the event loop (Node.js) or main thread

${context.ragContext ? `Knowledge base context:\n${context.ragContext}` : ''}`;
  }

  getUserPrompt(files: ClassifiedFile[], _context: AgentContext): string {
    return `Review these files for performance issues:\n\n${this.formatFiles(files)}`;
  }

  getEnrichmentSystemPrompt(_context: AgentContext): string {
    return `You are a performance specialist. Other agents have flagged findings with potential performance impact.
Quantify the impact when possible (e.g., O(n) vs O(n²), estimated latency increase).`;
  }

  getEnrichmentUserPrompt(referrals: CrossDomainReferral[], _context: AgentContext): string {
    const items = referrals.map(
      (r, i) => `### Referral ${i} (finding_index: ${r.findingIndex})
Reason: ${r.reason}
Code: ${r.contextSnippet}`,
    );
    return `Review these performance referrals:\n\n${items.join('\n\n')}`;
  }
}
