'use client'

import axios from 'axios'
import Link from 'next/link'
import { useState, useMemo, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { analysesApi, reposApi, type AnalysisResultPayload, type CrossrunSummary } from '@/lib/api'
import { useAnalysisProgress } from '@/hooks/useAnalysisProgress'
import { RepoWebLink } from '@/components/RepoWebLink'
import { ScmLogo } from '@/components/ScmLogo'
import { toast } from '@/components/Toast'
import { getScoreGrade, getScoreColor, getSeverityColor, cn } from '@/lib/utils'
import { InstrumentationRecommendationCard } from '@/components/InstrumentationRecommendationCard'
import { SuggestedFixDiff, suggestedFixIsNoOp } from '@/components/SuggestedFixDiff'
import { getInstrumentationRecommendation, hasNoInstrumentationFinding } from '@/lib/instrumentation-recommendation'

// ── Pillar/severity helpers ───────────────────────────────────────────────────

type SeverityFilter = 'all' | 'critical' | 'warning' | 'info'
type PillarFilter   = 'all' | 'metrics'  | 'logs'    | 'traces' | 'iac' | 'pipeline'

const SEVERITY_OPTIONS: { value: SeverityFilter; label: string }[] = [
  { value: 'all',      label: 'All severities' },
  { value: 'critical', label: 'Critical' },
  { value: 'warning',  label: 'Warning' },
  { value: 'info',     label: 'Info' },
]

const PILLAR_OPTIONS: { value: PillarFilter; label: string }[] = [
  { value: 'all',      label: 'All signals' },
  { value: 'metrics',  label: 'Metrics' },
  { value: 'logs',     label: 'Logs' },
  { value: 'traces',   label: 'Traces' },
  { value: 'iac',      label: 'IaC' },
  { value: 'pipeline', label: 'Pipeline' },
]

function countBySeverity(findings: Finding[], pillar?: string) {
  const filtered = pillar ? findings.filter(f => f.pillar === pillar) : findings
  return {
    critical: filtered.filter(f => f.severity === 'critical').length,
    warning:  filtered.filter(f => f.severity === 'warning').length,
    info:     filtered.filter(f => f.severity === 'info').length,
    total:    filtered.length,
  }
}

function scoreJustification(
  score: number | null,
  findings: Finding[],
  pillar?: string,
): string {
  if (score === null) return 'Not evaluated'
  if (score === 0) {
    const noInstr = findings.some(
      f => (pillar ? f.pillar === pillar : true) && (f as Record<string, unknown>).is_no_instrumentation
    )
    if (noInstr) return 'No instrumentation detected — score zeroed'
    const n = countBySeverity(findings, pillar)
    if (n.critical > 0) return `${n.critical} critical finding${n.critical > 1 ? 's' : ''} drove score to 0`
    return 'Major coverage gaps detected'
  }
  const n = countBySeverity(findings, pillar)
  if (n.total === 0) return 'No issues found — full coverage'
  const parts: string[] = []
  if (n.critical > 0) parts.push(`${n.critical} critical`)
  if (n.warning  > 0) parts.push(`${n.warning} warning`)
  if (n.info     > 0) parts.push(`${n.info} info`)
  return parts.join(' · ') + ` finding${n.total !== 1 ? 's' : ''}`
}

export default function AnalysisDetailPage({ params }: { params: { id: string } }) {
  const { id } = params
  const qc = useQueryClient()
  const streamHealthyRef = useRef(false)
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all')
  const [pillarFilter, setPillarFilter] = useState<PillarFilter>('all')

  const { data: job, isLoading } = useQuery({
    queryKey: ['analysis', id],
    queryFn: () => analysesApi.get(id),
    refetchInterval: (query) => {
      const j = query.state.data
      if (!j) return false
      if (j.status === 'running' || j.status === 'pending') {
        return streamHealthyRef.current ? false : 12000
      }
      if (j.fix_pr_pending && !j.fix_pr_url) return 3000
      return false
    },
  })

  const progressEnabled =
    !!job && (job.status === 'pending' || job.status === 'running')
  const {
    progressEvents,
    latestProgress,
    streamError,
    streaming,
    streamHealthy,
  } = useAnalysisProgress(id, progressEnabled)
  streamHealthyRef.current = streamHealthy

  const { data: repo } = useQuery({
    queryKey: ['repository', job?.repo_id],
    queryFn: () => reposApi.get(job!.repo_id),
    enabled: !!job?.repo_id && job.status === 'completed',
  })

  const fixPrMutation = useMutation({
    mutationFn: () => analysesApi.createFixPr(id),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['analysis', id] })
      if (data.status === 'enqueued') {
        toast(
          'Fix PR queued — generation runs in the background. You can leave this page; refresh later to open the PR link.',
          'success',
        )
      } else if (data.status === 'processing') {
        toast('A fix PR is already being generated. Status updates automatically.', 'info')
      } else if (data.status === 'already_created' && data.pr_url) {
        toast('Fix PR already exists for this analysis.', 'info')
      }
    },
    onError: (err: unknown) => {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : undefined
      toast(typeof detail === 'string' ? detail : 'Could not start fix PR. Try again.', 'error')
    },
  })

  const fixPrBusy = Boolean(job?.fix_pr_pending && !job?.fix_pr_url) || fixPrMutation.isPending

  if (isLoading) return <div className="p-8 text-gray-400 dark:text-gray-500">Loading...</div>
  if (!job) return <div className="p-8 text-red-500">Analysis not found.</div>

  const result: AnalysisResultPayload | null = job.result

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Analysis #{id.slice(0, 8)}</h1>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              job.status === 'completed' ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400' :
              job.status === 'running' ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400' :
              job.status === 'pending' ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300' :
              'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
            }`}>{job.status}</span>
          </div>

          {/* Fix PR — only offered when there are actionable recommendations (same rules as worker). */}
          {job.status === 'completed' && (
            job.fix_pr_url ? (
              <a
                href={job.fix_pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
                </svg>
                View Fix PR
              </a>
            ) : fixPrBusy ? (
              <button
                type="button"
                disabled
                className="inline-flex items-center gap-2 px-4 py-2 bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded-lg text-sm font-medium cursor-not-allowed"
                title="Fix PR is being generated in the background"
              >
                <span className="animate-spin w-4 h-4 border-2 border-gray-500 border-t-transparent rounded-full shrink-0" />
                Generating fix PR…
              </button>
            ) : job.fix_pr_eligible ? (
              <button
                type="button"
                onClick={() => fixPrMutation.mutate()}
                disabled={fixPrMutation.isPending}
                className="inline-flex items-center gap-2 px-4 py-2 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg text-sm font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                </svg>
                {fixPrMutation.isError ? 'Retry Fix PR' : 'Create Fix PR'}
              </button>
            ) : (
              <span
                className="text-xs text-gray-500 dark:text-gray-400 max-w-xs text-right"
                title="Requires at least one critical/warning finding on metrics, logs, or traces with a file path."
              >
                No recommendations eligible for a fix PR
              </span>
            )
          )}
        </div>
        <p className="text-gray-500 dark:text-gray-400 text-sm flex flex-wrap items-center gap-x-2 gap-y-1">
          {job.repo_full_name && (
            <span className="inline-flex items-center gap-2 font-medium text-gray-700 dark:text-gray-300">
              <ScmLogo scm={job.scm_type} className="h-5 w-5" />
              {job.repo_web_url ? (
                <RepoWebLink name={job.repo_full_name} href={job.repo_web_url} />
              ) : (
                job.repo_full_name
              )}
            </span>
          )}
          {job.repo_full_name && <span className="text-gray-400 dark:text-gray-500">·</span>}
          Trigger: {job.trigger} · Type: {job.analysis_type}
          {job.pr_number && ` · PR #${job.pr_number}`}
          {job.commit_sha && ` · ${job.commit_sha.slice(0, 7)}`}
        </p>

        {job.status === 'completed' && job.fix_pr_pending && !job.fix_pr_url && (
          <div
            className="mt-4 flex gap-3 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/40 px-4 py-3 text-sm text-blue-900 dark:text-blue-100"
            role="status"
            aria-live="polite"
          >
            <span className="mt-0.5 shrink-0 text-blue-500" aria-hidden>
              <svg className="w-5 h-5 animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </span>
            <div>
              <p className="font-medium">Fix PR is being generated</p>
              <p className="text-blue-800/90 dark:text-blue-200/90 mt-0.5 text-xs leading-relaxed">
                This runs in the background and may take a few minutes. You can refresh the page or come back later — the
                button stays disabled until the PR is ready. If generation fails, you can try again after a short wait.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Cross-run improvement vs previous completed analysis on same repo */}
      {job.status === 'completed' && result?.crossrun_summary && job.analysis_type !== 'context' && (() => {
        const cr = result.crossrun_summary as CrossrunSummary
        const prevId = cr.previous_job_id
        const sd = cr.score_delta
        return (
          <div className="mb-6 rounded-xl border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50/80 dark:bg-emerald-950/30 px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-emerald-900 dark:text-emerald-100">
                  Since last analysis
                </h2>
                <p className="text-xs text-emerald-800/90 dark:text-emerald-200/80 mt-1 max-w-2xl">
                  Compared to the previous completed run on this repository (same fingerprint heuristics). Re-run after merging
                  fixes to see resolved issues and score changes.
                </p>
              </div>
              {prevId && (
                <Link
                  href={`/analyses/${prevId}`}
                  className="text-xs font-medium text-emerald-700 dark:text-emerald-300 hover:underline shrink-0"
                >
                  Open previous analysis
                </Link>
              )}
            </div>
            <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
              <div className="rounded-lg bg-white/70 dark:bg-gray-900/50 px-3 py-2 border border-emerald-100 dark:border-emerald-900/40">
                <div className="text-2xl font-bold text-emerald-700 dark:text-emerald-300 tabular-nums">
                  {cr.resolved_count ?? 0}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-emerald-800/80 dark:text-emerald-400/90">Resolved</div>
              </div>
              <div className="rounded-lg bg-white/70 dark:bg-gray-900/50 px-3 py-2 border border-emerald-100 dark:border-emerald-900/40">
                <div className="text-2xl font-bold text-amber-700 dark:text-amber-300 tabular-nums">
                  {cr.new_count ?? 0}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-emerald-800/80 dark:text-emerald-400/90">New</div>
              </div>
              <div className="rounded-lg bg-white/70 dark:bg-gray-900/50 px-3 py-2 border border-emerald-100 dark:border-emerald-900/40">
                <div className="text-2xl font-bold text-slate-700 dark:text-slate-200 tabular-nums">
                  {cr.persisting_count ?? 0}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-emerald-800/80 dark:text-emerald-400/90">Still open</div>
              </div>
              <div className="rounded-lg bg-white/70 dark:bg-gray-900/50 px-3 py-2 border border-emerald-100 dark:border-emerald-900/40">
                <div
                  className={`text-2xl font-bold tabular-nums ${
                    sd == null
                      ? 'text-gray-500 dark:text-gray-400'
                      : sd > 0
                        ? 'text-green-600 dark:text-green-400'
                        : sd < 0
                          ? 'text-red-600 dark:text-red-400'
                          : 'text-slate-700 dark:text-slate-200'
                  }`}
                >
                  {sd == null ? '—' : sd > 0 ? `+${sd}` : sd}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-emerald-800/80 dark:text-emerald-400/90">Score Δ</div>
              </div>
            </div>
            {Array.isArray(cr.resolved) && cr.resolved.length > 0 && (
              <details className="mt-4 text-sm">
                <summary className="cursor-pointer text-emerald-800 dark:text-emerald-200 font-medium">
                  Resolved findings ({cr.resolved.length})
                </summary>
                <ul className="mt-2 space-y-1.5 text-emerald-900 dark:text-emerald-100/90 list-disc list-inside max-h-48 overflow-y-auto">
                  {cr.resolved.map((r, i) => (
                    <li key={`${r.fingerprint ?? i}-${i}`}>
                      <span className="font-medium">{(r.title ?? '').slice(0, 120)}</span>
                      {r.file_path && (
                        <span className="text-emerald-700/80 dark:text-emerald-300/80 text-xs ml-1">
                          ({r.file_path}
                          {r.line_start != null ? `:${r.line_start}` : ''})
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )
      })()}

      {/* Scores */}
      {result && (() => {
        const allFindings = (result.findings ?? []) as Finding[]
        const scorePillars: { label: string; score: number | null; pillar?: string }[] = [
          { label: 'Global',  score: result.score_global,  pillar: undefined },
          { label: 'Metrics', score: result.score_metrics, pillar: 'metrics' },
          { label: 'Logs',    score: result.score_logs,    pillar: 'logs' },
          { label: 'Traces',  score: result.score_traces,  pillar: 'traces' },
        ]
        return (
          <div className="grid grid-cols-4 gap-4 mb-6">
            {scorePillars.map(({ label, score, pillar }) => {
              const counts  = countBySeverity(allFindings, pillar)
              const justify = scoreJustification(score, allFindings, pillar)
              const isZero  = score === 0
              return (
                <div
                  key={label}
                  className={cn(
                    'bg-white dark:bg-gray-900 p-5 rounded-xl border text-center flex flex-col gap-1',
                    isZero
                      ? 'border-red-200 dark:border-red-900/50'
                      : 'border-gray-200 dark:border-gray-700',
                  )}
                >
                  <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">{label}</div>
                  <div className={`text-4xl font-bold ${score != null ? getScoreColor(score) : 'text-gray-400 dark:text-gray-600'}`}>
                    {score ?? '—'}
                  </div>
                  {score != null && (
                    <div className="text-sm text-gray-400 dark:text-gray-500">({getScoreGrade(score)})</div>
                  )}

                  {/* Justification */}
                  <div className={cn(
                    'mt-2 rounded-md px-2 py-1.5 text-xs leading-snug',
                    isZero
                      ? 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
                      : 'bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400',
                  )}>
                    {justify}
                  </div>

                  {/* Severity mini-pills */}
                  {counts.total > 0 && (
                    <div className="flex items-center justify-center gap-1 mt-1 flex-wrap">
                      {counts.critical > 0 && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 font-medium tabular-nums">
                          {counts.critical} critical
                        </span>
                      )}
                      {counts.warning > 0 && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 font-medium tabular-nums">
                          {counts.warning} warning
                        </span>
                      )}
                      {counts.info > 0 && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 font-medium tabular-nums">
                          {counts.info} info
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )
      })()}

      {/* Score reference — collapsed by default */}
      {result && (
        <details className="mb-8 border border-gray-100 dark:border-gray-800 rounded-lg overflow-hidden group">
          <summary className="flex items-center gap-2 px-4 py-3 cursor-pointer select-none text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors">
            <svg className="w-3.5 h-3.5 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            Scoring reference
          </summary>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-t border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50">
                <th className="px-3 py-2 text-left font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide">Grade</th>
                <th className="px-3 py-2 text-left font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide">Range</th>
                <th className="px-3 py-2 text-left font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide">Meaning</th>
                <th className="px-3 py-2 text-left font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide">Score impact</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {[
                { grade: 'A', range: '90–100', color: 'text-green-500', meaning: 'Excellent — production-ready observability', impact: 'No critical or warning findings' },
                { grade: 'B', range: '75–89',  color: 'text-blue-500',  meaning: 'Good coverage with minor gaps',           impact: '–10 per warning, –3 per info' },
                { grade: 'C', range: '60–74',  color: 'text-yellow-500',meaning: 'Partial — key signals missing or noisy',  impact: 'Multiple warnings or 1–2 critical' },
                { grade: 'D', range: '0–59',   color: 'text-red-500',   meaning: 'Poor — high production risk',             impact: '–25 per critical finding' },
              ].map(({ grade, range, color, meaning, impact }) => (
                <tr key={grade} className="text-gray-500 dark:text-gray-400">
                  <td className={`px-3 py-2 font-bold ${color}`}>{grade}</td>
                  <td className="px-3 py-2 tabular-nums text-gray-400 dark:text-gray-500">{range}</td>
                  <td className="px-3 py-2">{meaning}</td>
                  <td className="px-3 py-2 text-gray-400 dark:text-gray-500">{impact}</td>
                </tr>
              ))}
              <tr className="text-gray-400 dark:text-gray-500 bg-gray-50/50 dark:bg-gray-800/30">
                <td className="px-3 py-2 font-bold text-red-500">0</td>
                <td className="px-3 py-2 tabular-nums">—</td>
                <td className="px-3 py-2">No instrumentation detected</td>
                <td className="px-3 py-2">Metrics & traces require an SDK or agent</td>
              </tr>
            </tbody>
          </table>
        </details>
      )}

      {/* Instrumentation recommendation — shown when agent confirmed no instrumentation */}
      {job.status === 'completed' && result && repo && (() => {
        const findings = (result.findings ?? []) as Array<Record<string, unknown>>
        if (!hasNoInstrumentationFinding(findings)) return null
        const rec = getInstrumentationRecommendation(repo, job)
        if (!rec) return null
        return (
          <div className="mb-6">
            <InstrumentationRecommendationCard recommendation={rec} />
          </div>
        )
      })()}

      {/* Findings */}
      {result?.findings && result.findings.length > 0 && (
        <FindingsSection
          findings={result.findings as Finding[]}
          jobId={id}
          severityFilter={severityFilter}
          setSeverityFilter={setSeverityFilter}
          pillarFilter={pillarFilter}
          setPillarFilter={setPillarFilter}
        />
      )}

      {(job.status === 'running' || job.status === 'pending') && (
        <div
          className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl p-6 text-left text-blue-900 dark:text-blue-100"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <h2 className="text-lg font-semibold">
                {streamError ? 'Analysis in progress (live stream unavailable)' : 'Analysis in progress'}
              </h2>
              <p className="text-sm text-blue-800/90 dark:text-blue-200/90 mt-1">
                {latestProgress?.message ??
                  (streaming ? 'Connecting to live progress…' : 'Waiting for the analysis worker…')}
              </p>
            </div>
            <div className="text-right text-sm tabular-nums shrink-0 text-blue-800 dark:text-blue-200">
              {latestProgress != null ? `${Math.min(100, Math.max(0, latestProgress.progress_pct))}%` : '—'}
            </div>
          </div>
          <div className="h-2 bg-blue-200/60 dark:bg-blue-950 rounded-full overflow-hidden mb-4">
            <div
              className="h-full bg-blue-600 dark:bg-blue-400 transition-all duration-300 ease-out rounded-full"
              style={{
                width: `${Math.min(100, Math.max(0, latestProgress?.progress_pct ?? 0))}%`,
              }}
            />
          </div>
          {streamError && (
            <p className="text-xs text-amber-800 dark:text-amber-200 mb-3">
              Could not open live stream ({streamError}). Status still refreshes about every 12s until complete.
            </p>
          )}
          <div className="max-h-52 overflow-y-auto space-y-1.5 text-sm border-t border-blue-200/50 dark:border-blue-800/50 pt-3">
            {progressEvents.length === 0 ? (
              <p className="text-blue-700/70 dark:text-blue-300/70 italic text-sm">
                {streaming ? 'Connecting…' : 'No step updates yet.'}
              </p>
            ) : (
              progressEvents.map((e, i) => (
                <div
                  key={`${e.timestamp ?? ''}-${i}-${e.message.slice(0, 24)}`}
                  className={cn(
                    'flex gap-2',
                    i === progressEvents.length - 1 && 'font-medium',
                  )}
                >
                  <span className="shrink-0 text-[11px] uppercase tracking-wide text-blue-600 dark:text-blue-400 w-[5.5rem]">
                    {e.stage}
                  </span>
                  <span className="min-w-0 text-blue-900 dark:text-blue-100">{e.message}</span>
                </div>
              ))
            )}
          </div>
          <p className="text-xs text-blue-700/80 dark:text-blue-300/80 mt-4">
            Results will appear below when the analysis completes.
          </p>
        </div>
      )}

      {job.status === 'completed' && !result && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-6 rounded-xl text-amber-900 dark:text-amber-400 text-sm">
          No scores or findings were returned for this run. If this is an older analysis, run a new one;
          otherwise check API/worker logs for save errors.
        </div>
      )}
    </div>
  )
}

type FeedbackSignal = 'thumbs_up' | 'thumbs_down' | 'ignored' | 'applied'

interface Finding {
  id?: string
  pillar: string
  severity: string
  dimension: string
  title: string
  description: string
  file_path?: string
  line_start?: number
  suggestion?: string
  /** Actual problematic code extracted from the repository file */
  code_before?: string
  /** Corrected version of the problematic code */
  code_after?: string
  estimated_monthly_cost_impact?: number
  is_new?: boolean
  /** Set by agent diff_crossrun when a prior run exists for the repo */
  crossrun_status?: 'new' | 'persisting'
}

/** Persisted findings use UUID ids; JSONB snapshots may omit id or use the string "None". */
function isValidFindingId(id?: string): boolean {
  const raw = id?.trim()
  if (!raw || raw === 'None' || raw === 'null' || raw === 'undefined') return false
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(raw)
}

/** Avoid duplicate React keys when ids are missing or invalid. */
function stableFindingKey(f: Finding, index: number, jobId: string): string {
  if (isValidFindingId(f.id)) return f.id!.trim()
  const tail = `${f.pillar}|${f.file_path ?? ''}|${f.line_start ?? ''}|${f.title}`.slice(0, 200)
  return `${jobId}-f${index}-${tail}`
}

// ── FindingsSection with filter bar ─────────────────────────────────────────

function FindingsSection({
  findings,
  jobId,
  severityFilter,
  setSeverityFilter,
  pillarFilter,
  setPillarFilter,
}: {
  findings: Finding[]
  jobId: string
  severityFilter: SeverityFilter
  setSeverityFilter: (v: SeverityFilter) => void
  pillarFilter: PillarFilter
  setPillarFilter: (v: PillarFilter) => void
}) {
  const filtered = useMemo(() => findings.filter(f => {
    if (severityFilter !== 'all' && f.severity !== severityFilter) return false
    if (pillarFilter   !== 'all' && f.pillar   !== pillarFilter)   return false
    return true
  }), [findings, severityFilter, pillarFilter])

  const isNewFinding = (f: Finding) =>
    f.crossrun_status === 'new' || (f.crossrun_status == null && f.is_new === true)
  const isPersisting = (f: Finding) =>
    f.crossrun_status === 'persisting' || (f.crossrun_status == null && f.is_new === false)

  const newCount       = findings.filter(isNewFinding).length
  const persistingCount = findings.filter(isPersisting).length
  const hasNewInfo     = findings.some(f => f.is_new !== undefined || f.crossrun_status !== undefined)
  const isFiltered     = severityFilter !== 'all' || pillarFilter !== 'all'

  // Available pills — only show pillars/severities that have at least one finding
  const availablePillars   = useMemo(() => {
    const set = new Set(findings.map(f => f.pillar))
    return PILLAR_OPTIONS.filter(o => o.value === 'all' || set.has(o.value))
  }, [findings])

  const availableSeverities = useMemo(() => {
    const set = new Set(findings.map(f => f.severity))
    return SEVERITY_OPTIONS.filter(o => o.value === 'all' || set.has(o.value))
  }, [findings])

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
      {/* Header */}
      <div className="px-5 pt-5 pb-4 border-b border-gray-200 dark:border-gray-700 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100">
            Findings
            <span className="ml-2 text-sm font-normal text-gray-400 dark:text-gray-500">
              {isFiltered
                ? `${filtered.length} of ${findings.length}`
                : findings.length}
            </span>
          </h2>
          <div className="flex items-center gap-3">
            {hasNewInfo && (
              <span className="text-xs text-gray-500 dark:text-gray-400">
                <span className="text-green-600 dark:text-green-400 font-medium">{newCount} new</span>
                {' · '}
                <span>{persistingCount} persisting</span>
              </span>
            )}
            {isFiltered && (
              <button
                type="button"
                onClick={() => { setSeverityFilter('all'); setPillarFilter('all') }}
                className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 underline underline-offset-2"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>

        {/* Filter chips */}
        <div className="flex flex-wrap gap-4">
          {/* Severity */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0">Priority</span>
            <div className="flex gap-1">
              {availableSeverities.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setSeverityFilter(value)}
                  className={cn(
                    'px-2.5 py-1 rounded-full text-xs font-medium transition-colors',
                    severityFilter === value
                      ? value === 'critical'
                        ? 'bg-red-600 text-white'
                        : value === 'warning'
                          ? 'bg-yellow-500 text-white'
                          : value === 'info'
                            ? 'bg-blue-500 text-white'
                            : 'bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="w-px bg-gray-200 dark:bg-gray-700 self-stretch hidden sm:block" />

          {/* Pillar */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0">Signal</span>
            <div className="flex gap-1 flex-wrap">
              {availablePillars.map(({ value, label }) => {
                const PILLAR_COLORS: Record<string, string> = {
                  metrics:  'bg-purple-600 text-white',
                  logs:     'bg-green-600 text-white',
                  traces:   'bg-indigo-600 text-white',
                  iac:      'bg-orange-500 text-white',
                  pipeline: 'bg-pink-500 text-white',
                }
                const active = pillarFilter === value
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setPillarFilter(value)}
                    className={cn(
                      'px-2.5 py-1 rounded-full text-xs font-medium transition-colors',
                      active
                        ? (PILLAR_COLORS[value] ?? 'bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900')
                        : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700',
                    )}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* List */}
      {filtered.length > 0 ? (
        <div className="divide-y divide-gray-100 dark:divide-gray-800">
          {filtered.map((f, i) => (
            <FindingCard key={stableFindingKey(f, i, jobId)} finding={f} jobId={jobId} />
          ))}
        </div>
      ) : (
        <div className="py-12 text-center text-sm text-gray-400 dark:text-gray-500">
          No findings match the selected filters.
          <button
            type="button"
            onClick={() => { setSeverityFilter('all'); setPillarFilter('all') }}
            className="ml-1.5 underline underline-offset-2 hover:text-gray-700 dark:hover:text-gray-300"
          >
            Clear filters
          </button>
        </div>
      )}
    </div>
  )
}

// Reusable inline thumbs-up / thumbs-down row
function FeedbackRow({
  label,
  findingId,
  jobId,
  targetType,
  signals,
}: {
  label: string
  findingId: string
  jobId: string
  targetType: 'finding' | 'suggestion'
  signals: { value: FeedbackSignal; icon: React.ReactNode; title: string; activeClass: string; hoverClass: string }[]
}) {
  const [active, setActive] = useState<FeedbackSignal | null>(null)
  const [busy, setBusy] = useState(false)

  const handle = async (signal: FeedbackSignal) => {
    if (busy || active) return
    setBusy(true)
    try {
      await analysesApi.submitFeedback(jobId, findingId, signal, targetType)
      setActive(signal)
    } catch {
      toast('Could not save feedback. Try again.', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs text-gray-400 dark:text-gray-500 select-none">{label}</span>
      {signals.map((s) => (
        <button
          key={s.value}
          type="button"
          onClick={() => handle(s.value)}
          disabled={busy || active !== null}
          title={s.title}
          className={`p-1 rounded transition-colors disabled:cursor-not-allowed ${
            active === s.value ? s.activeClass : `text-gray-400 dark:text-gray-500 ${s.hoverClass} disabled:opacity-40`
          }`}
        >
          {s.icon}
        </button>
      ))}
      {active && (
        <span className="text-xs text-gray-400 dark:text-gray-500 italic">
          {active === 'thumbs_up' && '👍 thanks!'}
          {active === 'thumbs_down' && '👎 noted'}
          {active === 'applied' && '✓ applied'}
          {active === 'ignored' && 'ignored'}
        </span>
      )}
    </div>
  )
}

const ThumbUpIcon = () => (
  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5" />
  </svg>
)

const ThumbDownIcon = () => (
  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M10 14H5.236a2 2 0 01-1.789-2.894l3.5-7A2 2 0 018.736 3h4.018a2 2 0 01.485.06l3.76.94m-7 10v5a2 2 0 002 2h.096c.5 0 .905-.405.905-.904 0-.715.211-1.413.608-2.008L17 13V4m-7 10h2m5-10h2a2 2 0 012 2v6a2 2 0 01-2 2h-2.5" />
  </svg>
)

const CheckIcon = () => (
  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
  </svg>
)

function FindingCard({ finding, jobId }: { finding: Finding; jobId: string }) {
  return (
    <div className="p-4">
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 shrink-0 px-2 py-0.5 rounded text-xs font-medium ${getSeverityColor(finding.severity)}`}>
          {finding.severity}
        </span>

        <div className="flex-1 min-w-0">
          {/* Header row: title + finding feedback inline */}
          <div className="flex items-start justify-between gap-3 mb-1">
            <div className="flex items-center flex-wrap gap-2 min-w-0">
              <span className="font-medium text-gray-900 dark:text-gray-100 text-sm">{finding.title}</span>
              {(finding.crossrun_status === 'new' || (finding.crossrun_status == null && finding.is_new === true)) && (
                <span className="text-xs font-medium text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-900/30 px-1.5 py-0.5 rounded shrink-0">
                  New
                </span>
              )}
              {finding.crossrun_status === 'persisting' && (
                <span className="text-xs font-medium text-amber-800 dark:text-amber-200 bg-amber-100 dark:bg-amber-900/30 px-1.5 py-0.5 rounded shrink-0">
                  Still open
                </span>
              )}
              <span className="text-xs text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded shrink-0">
                {finding.pillar}
              </span>
              {(finding.estimated_monthly_cost_impact ?? 0) > 0 && (
                <span className="text-xs text-orange-600 dark:text-orange-400 font-medium shrink-0">
                  ~${finding.estimated_monthly_cost_impact}/mo
                </span>
              )}
            </div>

            {/* Finding-level feedback: was this finding accurate? */}
            {isValidFindingId(finding.id) && (
              <div className="shrink-0">
                <FeedbackRow
                  label="Accurate?"
                  findingId={finding.id!}
                  jobId={jobId}
                  targetType="finding"
                  signals={[
                    {
                      value: 'thumbs_up',
                      icon: <ThumbUpIcon />,
                      title: 'Accurate finding — true positive',
                      activeClass: 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/30',
                      hoverClass: 'hover:text-green-600 dark:hover:text-green-400 hover:bg-green-50 dark:hover:bg-green-900/20',
                    },
                    {
                      value: 'thumbs_down',
                      icon: <ThumbDownIcon />,
                      title: 'False positive — not a real issue',
                      activeClass: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30',
                      hoverClass: 'hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20',
                    },
                  ]}
                />
              </div>
            )}
          </div>

          <p className="text-sm text-gray-600 dark:text-gray-400">{finding.description}</p>

          {finding.file_path && (
            <code className="text-xs text-gray-400 dark:text-gray-500 mt-1 block">
              {finding.file_path}:{finding.line_start}
            </code>
          )}

          {/* Suggestion section with its own feedback */}
          {(finding.suggestion || finding.code_before || finding.code_after) && (
            <div className="mt-3 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
              <details>
                <summary className="flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-gray-800/60 cursor-pointer select-none group">
                  <span className="text-xs font-medium text-gray-600 dark:text-gray-300 group-hover:text-gray-900 dark:group-hover:text-gray-100 transition-colors flex items-center gap-1.5">
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                    </svg>
                    {suggestedFixIsNoOp(finding) ? 'View code (no change — current matches suggested)' : 'View suggested fix'}
                  </span>
                  <svg className="w-3.5 h-3.5 text-gray-400 transition-transform group-open:rotate-180" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </summary>

                <div className="bg-[#0d1117] dark:bg-[#0d1117]">
                  <SuggestedFixDiff finding={finding} />
                </div>

                {/* Suggestion-level feedback */}
                {isValidFindingId(finding.id) && (
                  <div className="flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-gray-800/60 border-t border-gray-200 dark:border-gray-700">
                    <FeedbackRow
                      label="Was this fix helpful?"
                      findingId={finding.id!}
                      jobId={jobId}
                      targetType="suggestion"
                      signals={[
                        {
                          value: 'thumbs_up',
                          icon: <ThumbUpIcon />,
                          title: 'Helpful and correct fix',
                          activeClass: 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/30',
                          hoverClass: 'hover:text-green-600 dark:hover:text-green-400 hover:bg-green-50 dark:hover:bg-green-900/20',
                        },
                        {
                          value: 'thumbs_down',
                          icon: <ThumbDownIcon />,
                          title: 'Incorrect or unhelpful fix',
                          activeClass: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30',
                          hoverClass: 'hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20',
                        },
                        {
                          value: 'applied',
                          icon: <CheckIcon />,
                          title: 'Applied this fix to my code',
                          activeClass: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/30',
                          hoverClass: 'hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20',
                        },
                      ]}
                    />
                    <span className="text-xs text-gray-400 dark:text-gray-500 italic hidden sm:block">
                      Your feedback improves future analyses
                    </span>
                  </div>
                )}
              </details>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
