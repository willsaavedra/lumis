'use client'

import { useMemo } from 'react'
import type { AnalysisProgressEvent } from '@/lib/api'
import { cn } from '@/lib/utils'

const PIPELINE_STEPS: { id: string; stages: string[]; label: string }[] = [
  { id: 'clone', stages: ['cloning'], label: 'Clone' },
  { id: 'triage', stages: ['triaging'], label: 'Triage' },
  { id: 'parse', stages: ['parsing'], label: 'AST / graph' },
  { id: 'dd', stages: ['fetching_dd'], label: 'Datadog' },
  { id: 'rag', stages: ['retrieving'], label: 'RAG' },
  { id: 'analyze', stages: ['analyzing'], label: 'Coverage' },
  { id: 'dedupe', stages: ['deduplicating'], label: 'Dedupe' },
  { id: 'diff', stages: ['diffing'], label: 'Cross-run' },
  { id: 'score', stages: ['scoring'], label: 'Score' },
  { id: 'suggest', stages: ['generating'], label: 'Suggestions' },
  { id: 'save', stages: ['posting'], label: 'Save' },
  { id: 'done', stages: ['done'], label: 'Done' },
]

const CONTEXT_STEPS: { id: string; stages: string[]; label: string }[] = [
  { id: 'discover', stages: ['discovering'], label: 'Discovery' },
  { id: 'done', stages: ['done'], label: 'Done' },
]

function stepIndexForStage(stage: string, steps: typeof PIPELINE_STEPS): number {
  return steps.findIndex((s) => s.stages.includes(stage))
}

export function AnalysisPipeline({ events }: { events: AnalysisProgressEvent[] }) {
  const { list, activeIndex, failed } = useMemo(() => {
    const pipelineEvents = events.filter((e) => e.event_type !== 'llm')
    const last = pipelineEvents[pipelineEvents.length - 1]
    const stage = last?.stage ?? ''
    const isContext = events.some((e) => e.stage === 'discovering') && !events.some((e) => e.stage === 'triaging')
    const steps = isContext ? CONTEXT_STEPS : PIPELINE_STEPS
    if (stage === 'failed') {
      return { list: steps, activeIndex: -1, failed: true }
    }
    if (stage === 'done') {
      return { list: steps, activeIndex: steps.length - 1, failed: false }
    }
    const idx = stepIndexForStage(stage, steps)
    return { list: steps, activeIndex: idx >= 0 ? idx : 0, failed: false }
  }, [events])

  return (
    <div className="mb-4" aria-label="Analysis pipeline progress">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-800/80 dark:text-blue-200/80 mb-2">
        Pipeline
      </p>
      <div className="flex flex-wrap gap-y-2 gap-x-1 sm:gap-x-2 items-center">
        {list.map((s, i) => {
          const completed = !failed && activeIndex >= 0 && i < activeIndex
          const active = !failed && i === activeIndex
          const pending = !failed && activeIndex >= 0 && i > activeIndex
          return (
            <div key={s.id} className="flex items-center gap-1 sm:gap-2">
              {i > 0 && (
                <span className="text-blue-400 dark:text-blue-600 text-xs select-none" aria-hidden>
                  →
                </span>
              )}
              <span
                className={cn(
                  'px-2 py-1 rounded-md text-[10px] sm:text-xs font-medium border transition-colors',
                  failed && 'opacity-40',
                  completed && 'bg-emerald-100/90 dark:bg-emerald-900/40 border-emerald-300/80 dark:border-emerald-800 text-emerald-900 dark:text-emerald-100',
                  active && 'bg-blue-200/90 dark:bg-blue-900/50 border-blue-400 dark:border-blue-600 text-blue-950 dark:text-blue-50 ring-1 ring-blue-400/40',
                  pending && 'bg-white/50 dark:bg-gray-900/40 border-blue-200/60 dark:border-blue-900 text-blue-700/70 dark:text-blue-300/70',
                )}
              >
                {s.label}
              </span>
            </div>
          )
        })}
      </div>
      {failed && (
        <p className="text-xs text-red-700 dark:text-red-300 mt-2">Pipeline stopped — analysis failed.</p>
      )}
    </div>
  )
}
