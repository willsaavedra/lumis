'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { AnalysisProgressEvent, AgentProgressStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

type PipelineStepDef = {
  id: string
  label: string
  shortLabel: string
}

/** Ordered stages for the horizontal pipeline (matches agent-ts publishProgress stages). */
const PIPELINE: PipelineStepDef[] = [
  { id: 'starting', label: 'Kickoff', shortLabel: 'Start' },
  { id: 'cloning', label: 'Clone', shortLabel: 'Clone' },
  { id: 'triage', label: 'Triage', shortLabel: 'Triage' },
  { id: 'context_discovery', label: 'Context', shortLabel: 'Ctx' },
  { id: 'dispatching', label: 'Dispatch', shortLabel: 'Dispatch' },
  { id: 'retrieving_context', label: 'RAG', shortLabel: 'RAG' },
  { id: 'fetch_dd', label: 'Signals', shortLabel: 'DD' },
  { id: 'analyzing', label: 'Agents', shortLabel: 'Agents' },
  { id: 'collaboration', label: 'Review', shortLabel: 'Review' },
  { id: 'consolidating', label: 'Consolidate', shortLabel: 'Merge' },
  { id: 'efficiency', label: 'Efficiency', shortLabel: 'Perf' },
  { id: 'deduplicating', label: 'Dedup', shortLabel: 'Dedup' },
  { id: 'crossrun', label: 'History', shortLabel: 'Δ' },
  { id: 'scoring', label: 'Scores', shortLabel: 'Score' },
  { id: 'suggestions', label: 'Fixes', shortLabel: 'Fixes' },
  { id: 'done', label: 'Complete', shortLabel: 'Done' },
]

const ORDER = new Map(PIPELINE.map((s, i) => [s.id, i]))

function mapStageToPipelineId(stage: string): string {
  const s = stage.toLowerCase().trim()
  if (s === 'failed') return 'failed'
  if (s === 'done' || s === 'completed') return 'done'
  if (s === 'starting') return 'starting'
  if (s === 'cloning') return 'cloning'
  if (s === 'triage') return 'triage'
  if (s === 'context_discovery') return 'context_discovery'
  if (s === 'dispatching' || s === 'dispatch') return 'dispatching'
  if (s === 'retrieving_context') return 'retrieving_context'
  if (s === 'fetch_dd' || s === 'datadog') return 'fetch_dd'
  if (s === 'analyzing') return 'analyzing'
  if (s === 'collaboration') return 'collaboration'
  if (s === 'consolidating' || s === 'consolidate') return 'consolidating'
  if (s === 'efficiency') return 'efficiency'
  if (s === 'deduplicating' || s === 'deduplicate') return 'deduplicating'
  if (s === 'crossrun') return 'crossrun'
  if (s === 'scoring' || s === 'score') return 'scoring'
  if (s === 'suggestions' || s === 'suggestion') return 'suggestions'
  return 'analyzing'
}

type StepStatus = 'pending' | 'active' | 'done' | 'failed'

type LogLine = {
  id: string
  at: string
  stage: string
  message: string
}

function formatTime(iso?: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  } catch {
    return ''
  }
}

export function AnalysisLiveProgress({
  latestProgress,
  progressEvents,
  streaming,
  streamError,
  agentRoster,
  activeAgent,
  llmText,
  currentFiles,
}: {
  latestProgress: AnalysisProgressEvent | null
  progressEvents: AnalysisProgressEvent[]
  streaming: boolean
  streamError: string | null
  agentRoster: AgentProgressStatus[]
  activeAgent: string | null
  llmText?: string | null
  currentFiles?: string[]
}) {
  const [logExpanded, setLogExpanded] = useState(true)
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)
  const llmPanelRef = useRef<HTMLDivElement>(null!)

  const { stepStatuses, logLines, visiblePipeline, pipelineFailed } = useMemo(() => {
    // streaming is used for initial "connecting" UI state
    const connecting = streaming
    const logs: LogLine[] = []
    let fail = false
    let failAtIdx = PIPELINE.length - 1

    for (let i = 0; i < progressEvents.length; i++) {
      const e = progressEvents[i]
      if (e.progress_pct < 0) continue
      logs.push({
        id: `e-${i}`,
        at: e.timestamp ?? '',
        stage: e.stage,
        message: e.message,
      })
      if (e.stage.toLowerCase() === 'failed') {
        fail = true
        const prev = progressEvents
          .slice(0, i)
          .filter((x) => x.progress_pct >= 0 && x.stage.toLowerCase() !== 'failed')
          .at(-1)
        if (prev) {
          const p = mapStageToPipelineId(prev.stage)
          failAtIdx = ORDER.get(p) ?? failAtIdx
        }
      }
    }

    const latest = progressEvents.filter((e) => e.progress_pct >= 0).at(-1)
    const statuses: Record<string, StepStatus> = {}

    let maxSeenIdx = 0
    for (const e of progressEvents) {
      if (e.progress_pct < 0) continue
      const pid = mapStageToPipelineId(e.stage)
      if (pid === 'done' || pid === 'failed') continue
      maxSeenIdx = Math.max(maxSeenIdx, ORDER.get(pid) ?? 0)
    }

    const allDone = latest && mapStageToPipelineId(latest.stage) === 'done'

    if (allDone) {
      for (const step of PIPELINE) {
        statuses[step.id] = 'done'
      }
    } else if (fail && latest?.stage.toLowerCase() === 'failed') {
      for (const step of PIPELINE) {
        const i = ORDER.get(step.id)!
        if (i < failAtIdx) statuses[step.id] = 'done'
        else if (i === failAtIdx) statuses[step.id] = 'failed'
        else statuses[step.id] = 'pending'
      }
    } else if (progressEvents.length > 0) {
      for (const step of PIPELINE) {
        const i = ORDER.get(step.id)!
        if (i < maxSeenIdx) statuses[step.id] = 'done'
        else if (i === maxSeenIdx) statuses[step.id] = 'active'
        else statuses[step.id] = 'pending'
      }
    } else if (connecting) {
      for (const step of PIPELINE) {
        statuses[step.id] = step.id === 'starting' ? 'active' : 'pending'
      }
    } else {
      for (const step of PIPELINE) {
        statuses[step.id] = 'pending'
      }
    }

    let visibleEnd = allDone ? PIPELINE.length : Math.min(PIPELINE.length, maxSeenIdx + 3)
    if (fail) visibleEnd = Math.min(PIPELINE.length, failAtIdx + 3)
    const visible = PIPELINE.slice(0, Math.max(6, visibleEnd))

    return {
      stepStatuses: statuses,
      pipelineFailed: fail,
      logLines: logs.slice(-80),
      visiblePipeline: visible,
    }
  }, [progressEvents, streaming])

  const pct = latestProgress != null && latestProgress.progress_pct >= 0
    ? Math.min(100, Math.max(0, latestProgress.progress_pct))
    : 0

  const filteredLogForStep =
    selectedStepId == null
      ? logLines
      : logLines.filter((l) => mapStageToPipelineId(l.stage) === selectedStepId)

  return (
    <div
      className="rounded-xl border border-blue-200/80 dark:border-blue-800/80 bg-gradient-to-b from-blue-50/90 to-white/80 dark:from-blue-950/40 dark:to-gray-950/90 text-blue-950 dark:text-blue-50 shadow-sm overflow-hidden"
      role="status"
      aria-live="polite"
    >
      {/* Header + progress bar */}
      <div className="px-5 pt-5 pb-4 border-b border-blue-100/80 dark:border-blue-900/50">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-gray-900 dark:text-gray-50">
              {streamError ? 'Analysis running (live stream limited)' : 'Live analysis'}
            </h2>
            <p className="text-sm text-blue-800/85 dark:text-blue-200/85 mt-0.5">
              {latestProgress?.message ??
                (streaming ? 'Connecting to the analysis pipeline…' : 'Waiting for the worker…')}
            </p>
          </div>
          <div className="text-right shrink-0">
            <div className="text-2xl font-semibold tabular-nums text-blue-700 dark:text-blue-300">
              {latestProgress != null && latestProgress.progress_pct >= 0 ? `${pct}%` : '—'}
            </div>
            <div className="text-[10px] uppercase tracking-wider text-blue-600/70 dark:text-blue-400/60">
              progress
            </div>
          </div>
        </div>
        <div className="h-2 rounded-full bg-blue-200/50 dark:bg-blue-950 overflow-hidden ring-1 ring-inset ring-blue-300/30 dark:ring-blue-800/40">
          <div
            className="h-full rounded-full bg-gradient-to-r from-blue-500 to-indigo-500 dark:from-blue-400 dark:to-indigo-400 transition-[width] duration-500 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        {streamError && (
          <p className="text-xs text-amber-800 dark:text-amber-200/90 mt-3 flex items-center gap-2">
            <span className="inline-flex h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
            Stream unavailable ({streamError}). Status still refreshes periodically.
          </p>
        )}
        {pipelineFailed && (
          <p className="text-xs text-red-700 dark:text-red-300/90 mt-2 flex items-center gap-2">
            <span className="inline-flex h-1.5 w-1.5 rounded-full bg-red-500" />
            Pipeline reported a failure — check the activity log below.
          </p>
        )}
      </div>

      {/* Pipeline diagram */}
      <div className="px-3 sm:px-5 py-4 overflow-x-auto">
        <div className="flex items-center min-w-max gap-0 pb-1">
          {visiblePipeline.map((step, i) => {
            const st = stepStatuses[step.id] ?? 'pending'
            const isLast = i === visiblePipeline.length - 1
            return (
              <div key={step.id} className="flex items-center">
                <button
                  type="button"
                  onClick={() => setSelectedStepId((v) => (v === step.id ? null : step.id))}
                  className={cn(
                    'group flex flex-col items-center gap-1.5 min-w-[3.25rem] sm:min-w-[4rem] px-1 rounded-lg py-1 transition-colors',
                    selectedStepId === step.id ? 'bg-blue-100/80 dark:bg-blue-900/40' : 'hover:bg-blue-50/50 dark:hover:bg-blue-950/30',
                  )}
                  title={`${step.label} — click to filter log`}
                >
                  <span
                    className={cn(
                      'relative flex h-8 w-8 sm:h-9 sm:w-9 items-center justify-center rounded-full border-2 text-[10px] sm:text-xs font-semibold transition-all duration-300',
                      st === 'done' &&
                        'border-emerald-400 bg-emerald-50 text-emerald-700 dark:border-emerald-500/60 dark:bg-emerald-950/50 dark:text-emerald-300',
                      st === 'active' &&
                        'border-blue-500 bg-blue-100 text-blue-800 shadow-[0_0_0_3px_rgba(59,130,246,0.25)] dark:border-blue-400 dark:bg-blue-950 dark:text-blue-100',
                      st === 'failed' &&
                        'border-red-400 bg-red-50 text-red-700 dark:border-red-500 dark:bg-red-950/50 dark:text-red-200',
                      st === 'pending' &&
                        'border-blue-200/60 bg-white/80 text-blue-300 dark:border-blue-900 dark:bg-gray-900/80 dark:text-blue-600',
                    )}
                  >
                    {st === 'done' && (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                    {st === 'active' && (
                      <span className="relative flex h-2.5 w-2.5">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-60" />
                        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-blue-600 dark:bg-blue-300" />
                      </span>
                    )}
                    {st === 'failed' && (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    )}
                    {st === 'pending' && <span className="opacity-50">{i + 1}</span>}
                  </span>
                  <span
                    className={cn(
                      'text-[9px] sm:text-[10px] font-medium text-center leading-tight max-w-[4.5rem] sm:max-w-[5.5rem]',
                      st === 'active' ? 'text-blue-900 dark:text-blue-100' : 'text-blue-700/80 dark:text-blue-300/80',
                    )}
                  >
                    <span className="sm:hidden">{step.shortLabel}</span>
                    <span className="hidden sm:inline">{step.label}</span>
                  </span>
                </button>
                {!isLast && (
                  <div
                    className={cn(
                      'h-0.5 w-3 sm:w-5 shrink-0 rounded-full transition-colors duration-500',
                      stepStatuses[visiblePipeline[i + 1]?.id] === 'pending' &&
                        stepStatuses[step.id] !== 'pending'
                        ? 'bg-gradient-to-r from-emerald-400 to-blue-200/50 dark:from-emerald-600 dark:to-blue-900'
                        : stepStatuses[step.id] === 'done'
                          ? 'bg-emerald-400/80 dark:bg-emerald-600/60'
                          : 'bg-blue-200/60 dark:bg-blue-900/60',
                    )}
                    aria-hidden
                  />
                )}
              </div>
            )
          })}
        </div>
        <p className="text-[10px] text-blue-600/70 dark:text-blue-400/50 mt-2 text-center sm:text-left px-1">
          Pipeline fills left to right as each stage runs. Click a step to filter the activity log.
        </p>
      </div>

      {/* Agent activity (compact) */}
      {agentRoster.length > 0 && (
        <div className="mx-3 sm:mx-5 mb-3 rounded-lg border border-blue-200/50 dark:border-blue-800/40 bg-white/60 dark:bg-gray-900/40 overflow-hidden">
          <div className="px-3 py-2 flex items-center justify-between border-b border-blue-100/80 dark:border-blue-900/40">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-blue-800 dark:text-blue-300">
              Agents
            </span>
            <span className="text-[10px] tabular-nums text-blue-600/80 dark:text-blue-400/70">
              {agentRoster.filter((a) => a.status === 'completed').length}/{agentRoster.length} done
            </span>
          </div>
          <div className="max-h-36 overflow-y-auto divide-y divide-blue-50 dark:divide-blue-950/50">
            {agentRoster
              .sort((a, b) => {
                const order: Record<string, number> = { streaming: 0, running: 1, queued: 2, completed: 3, failed: 4 }
                return (order[a.status] ?? 5) - (order[b.status] ?? 5)
              })
              .map((agent) => (
                <div
                  key={agent.name}
                  className={cn(
                    'px-3 py-1.5 flex items-center gap-2 text-xs',
                    activeAgent === agent.name && (agent.status === 'running' || agent.status === 'streaming')
                      ? 'bg-blue-50/90 dark:bg-blue-950/50'
                      : '',
                  )}
                >
                  <span className="shrink-0 w-4 flex justify-center">
                    {agent.status === 'completed' && (
                      <span className="text-emerald-500">✓</span>
                    )}
                    {(agent.status === 'running' || agent.status === 'streaming') && (
                      <span className="inline-block h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
                    )}
                    {agent.status === 'queued' && <span className="text-blue-300">○</span>}
                    {agent.status === 'failed' && <span className="text-red-500">✕</span>}
                  </span>
                  <span className="font-mono text-[11px] truncate text-blue-900 dark:text-blue-100">{agent.name}</span>
                  {agent.status === 'completed' && agent.findingsCount != null && (
                    <span className="ml-auto text-[10px] text-blue-600/70 tabular-nums">{agent.findingsCount} findings</span>
                  )}
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Current files + LLM reasoning */}
      {(llmText || (currentFiles && currentFiles.length > 0)) && (
        <div className="mx-3 sm:mx-5 mb-3 space-y-3">
          {currentFiles && currentFiles.length > 0 && (
            <div className="rounded-lg border border-blue-200/50 dark:border-blue-800/40 bg-white/60 dark:bg-gray-900/40 overflow-hidden">
              <div className="px-3 py-2 border-b border-blue-100/80 dark:border-blue-900/40">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-blue-800 dark:text-blue-300">
                  Analyzing files
                </span>
              </div>
              <div className="px-3 py-2 flex flex-wrap gap-1.5">
                {currentFiles.map((f) => (
                  <span
                    key={f}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-blue-100/80 dark:bg-blue-900/40 text-[10px] font-mono text-blue-800 dark:text-blue-200 border border-blue-200/60 dark:border-blue-800/50"
                  >
                    <svg className="w-3 h-3 opacity-60 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    {f.split('/').slice(-2).join('/')}
                  </span>
                ))}
              </div>
            </div>
          )}

          {llmText && (
            <LlmReasoningPanel text={llmText} panelRef={llmPanelRef} />
          )}
        </div>
      )}

      {/* Activity log — terminal inspired */}
      <div className="border-t border-blue-200/60 dark:border-blue-900/50 bg-gray-950/[0.03] dark:bg-black/20">
        <button
          type="button"
          onClick={() => setLogExpanded((v) => !v)}
          className="w-full px-4 py-2 flex items-center justify-between text-left text-xs font-medium text-blue-900 dark:text-blue-200 hover:bg-blue-50/50 dark:hover:bg-blue-950/30 transition-colors"
        >
          <span className="flex items-center gap-2">
            <svg className="w-3.5 h-3.5 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h7" />
            </svg>
            Activity log
            {selectedStepId && (
              <span className="text-[10px] font-normal text-blue-600 dark:text-blue-400">
                · filtered: {PIPELINE.find((s) => s.id === selectedStepId)?.label ?? selectedStepId}
              </span>
            )}
          </span>
          <span className="text-blue-500 text-[10px]">{logExpanded ? 'Hide' : 'Show'}</span>
        </button>
        {logExpanded && (
          <div className="px-3 pb-3">
            <div className="rounded-lg border border-gray-800/20 dark:border-gray-700/50 bg-[#0d1117] text-gray-100 font-mono text-[11px] leading-relaxed overflow-hidden shadow-inner">
              <div className="flex items-center gap-2 px-3 py-1.5 border-b border-gray-800/80 bg-gray-900/50 text-[10px] text-gray-500">
                <span className="h-2 w-2 rounded-full bg-red-500/90" />
                <span className="h-2 w-2 rounded-full bg-amber-400/90" />
                <span className="h-2 w-2 rounded-full bg-emerald-500/90" />
                <span className="ml-2 text-gray-600">lumis-agent · stream</span>
              </div>
              <div className="max-h-52 overflow-y-auto p-3 space-y-1.5">
                {filteredLogForStep.length === 0 ? (
                  <p className="text-gray-500 italic">
                    {streaming ? 'Waiting for events…' : 'No log lines yet.'}
                  </p>
                ) : (
                  filteredLogForStep.map((line) => (
                    <div key={line.id} className="flex gap-2 flex-wrap items-baseline">
                      <span className="text-gray-500 shrink-0 tabular-nums">
                        {formatTime(line.at) || '·'}
                      </span>
                      <span className="text-sky-400/90 shrink-0">[{line.stage}]</span>
                      <span className="text-gray-300 break-all min-w-0">{line.message}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
            {selectedStepId && (
              <button
                type="button"
                onClick={() => setSelectedStepId(null)}
                className="mt-2 text-[10px] text-blue-600 dark:text-blue-400 hover:underline"
              >
                Clear filter — show all steps
              </button>
            )}
          </div>
        )}
      </div>

      <p className="px-5 py-3 text-[11px] text-blue-700/75 dark:text-blue-300/60 border-t border-blue-100/80 dark:border-blue-900/40">
        Results and scores appear below when the run finishes.
      </p>
    </div>
  )
}

function LlmReasoningPanel({
  text,
  panelRef,
}: {
  text: string
  panelRef: React.RefObject<HTMLDivElement>
}) {
  const [expanded, setExpanded] = useState(true)

  useEffect(() => {
    if (panelRef.current) {
      panelRef.current.scrollTop = panelRef.current.scrollHeight
    }
  }, [text, panelRef])

  return (
    <div className="rounded-lg border border-indigo-200/50 dark:border-indigo-800/40 bg-white/60 dark:bg-gray-900/40 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-3 py-2 flex items-center justify-between text-left border-b border-indigo-100/80 dark:border-indigo-900/40 hover:bg-indigo-50/30 dark:hover:bg-indigo-950/20 transition-colors"
      >
        <span className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-60" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500" />
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-800 dark:text-indigo-300">
            LLM reasoning (live)
          </span>
        </span>
        <span className="text-indigo-500 text-[10px]">{expanded ? 'Hide' : 'Show'}</span>
      </button>
      {expanded && (
        <div
          ref={panelRef}
          className="max-h-64 overflow-y-auto p-3 bg-[#0d1117] font-mono text-[11px] leading-relaxed text-gray-300 whitespace-pre-wrap break-words"
        >
          {text}
          <span className="inline-block w-1.5 h-3.5 bg-indigo-400 animate-pulse ml-0.5 align-text-bottom" />
        </div>
      )}
    </div>
  )
}
