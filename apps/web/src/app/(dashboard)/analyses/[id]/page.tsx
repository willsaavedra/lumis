'use client'

import axios from 'axios'
import Link from 'next/link'
import { useState, useMemo, useRef, type CSSProperties } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { analysesApi, reposApi, type AnalysisResultPayload, type CrossrunSummary } from '@/lib/api'
import { useAnalysisProgress } from '@/hooks/useAnalysisProgress'
import { RepoWebLink } from '@/components/RepoWebLink'
import { ScmLogo } from '@/components/ScmLogo'
import { toast } from '@/components/Toast'
import { getScoreGrade, hzGradeColorVar, hzSeverityTokens, formatLlmProvider } from '@/lib/utils'
import { HzStatusBadge } from '@/components/HzStatusBadge'
import { AnalysisPipeline } from '@/components/AnalysisPipeline'
import { InstrumentationRecommendationCard } from '@/components/InstrumentationRecommendationCard'
import { SuggestedFixDiff, suggestedFixIsNoOp } from '@/components/SuggestedFixDiff'
import { getInstrumentationRecommendation, hasNoInstrumentationFinding } from '@/lib/instrumentation-recommendation'

// ── LLM provider helpers ─────────────────────────────────────────────────────

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
      f => (pillar ? f.pillar === pillar : true) && Boolean((f as unknown as Record<string, unknown>).is_no_instrumentation),
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

  if (isLoading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span className="hz-cursor" style={{ opacity: 0.4 }} aria-hidden />
      </div>
    )
  }
  if (!job) {
    return (
      <div style={{ padding: '24px', color: 'var(--hz-crit)', fontSize: '13px' }}>Analysis not found.</div>
    )
  }

  const result: AnalysisResultPayload | null = job.result

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%', background: 'var(--hz-bg)' }}>
      {/* Topbar + actions */}
      <div
        style={{
          padding: '18px 24px 14px',
          borderBottom: '1px solid var(--hz-rule)',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '12px',
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '10px' }}>
            <h1 className="hz-h2" style={{ margin: 0, color: 'var(--hz-ink)' }}>
              Analysis #{id.slice(0, 8)}
            </h1>
            <HzStatusBadge status={job.status} />
          </div>
          <p
            className="hz-body"
            style={{
              marginTop: '8px',
              marginBottom: 0,
              display: 'flex',
              flexWrap: 'wrap',
              alignItems: 'center',
              gap: '6px 8px',
              fontSize: '12px',
              color: 'var(--hz-muted)',
            }}
          >
            {job.repo_full_name && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', color: 'var(--hz-ink2)', fontWeight: 500 }}>
                <ScmLogo scm={job.scm_type} className="h-5 w-5 shrink-0" />
                {job.repo_web_url ? (
                  <RepoWebLink name={job.repo_full_name} href={job.repo_web_url} />
                ) : (
                  job.repo_full_name
                )}
              </span>
            )}
            {job.repo_full_name && <span style={{ color: 'var(--hz-rule2)' }}>·</span>}
            <span>
              Trigger: {job.trigger} · Type: {job.analysis_type}
              {job.pr_number != null && ` · PR #${job.pr_number}`}
              {job.commit_sha && ` · ${job.commit_sha.slice(0, 7)}`}
            </span>
            <span style={{ color: 'var(--hz-rule2)' }}>·</span>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                padding: '2px 8px',
                borderRadius: 'var(--hz-sm)',
                fontSize: '11px',
                fontWeight: 500,
                background: 'var(--hz-bg3)',
                color: 'var(--hz-ink2)',
                border: '1px solid var(--hz-rule)',
              }}
              title="LLM backend used for this analysis"
            >
              {formatLlmProvider(job.llm_provider)}
            </span>
          </p>
        </div>

        <div style={{ display: 'flex', flexShrink: 0, flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
          {job.status === 'completed' && (
            job.fix_pr_url ? (
              <a
                href={job.fix_pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="hz-btn hz-btn-primary inline-flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden>
                  <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
                </svg>
                View Fix PR
              </a>
            ) : fixPrBusy ? (
              <button
                type="button"
                disabled
                className="hz-btn hz-btn-ghost inline-flex items-center gap-2 opacity-60 cursor-not-allowed"
                title="Fix PR is being generated in the background"
              >
                <span
                  className="inline-block w-4 h-4 shrink-0 rounded-full border-2 border-t-transparent animate-spin"
                  style={{ borderColor: 'var(--hz-rule2)', borderTopColor: 'transparent' }}
                  aria-hidden
                />
                Generating fix PR…
              </button>
            ) : job.fix_pr_eligible ? (
              <button
                type="button"
                onClick={() => fixPrMutation.mutate()}
                disabled={fixPrMutation.isPending}
                className="hz-btn hz-btn-primary inline-flex items-center gap-2 disabled:opacity-50"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                </svg>
                {fixPrMutation.isError ? 'Retry Fix PR' : 'Create Fix PR'}
              </button>
            ) : (
              <span
                className="hz-sm max-w-xs text-right"
                style={{ color: 'var(--hz-muted)' }}
                title="Requires at least one critical/warning finding on metrics, logs, or traces with a file path."
              >
                No recommendations eligible for a fix PR
              </span>
            )
          )}
        </div>
      </div>

      {job.status === 'completed' && job.fix_pr_pending && !job.fix_pr_url && (
        <div
          style={{
            margin: '0',
            padding: '12px 24px',
            display: 'flex',
            gap: '12px',
            borderBottom: '1px solid var(--hz-rule)',
            background: 'var(--hz-info-bg)',
            color: 'var(--hz-info)',
          }}
          role="status"
          aria-live="polite"
        >
          <span style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden>
            <svg className="w-5 h-5" style={{ animation: 'hz-pulse 1s ease infinite' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </span>
          <div>
            <p style={{ fontSize: '13px', fontWeight: 500, margin: 0, color: 'var(--hz-ink2)' }}>Fix PR is being generated</p>
            <p className="hz-sm" style={{ marginTop: '4px', marginBottom: 0, lineHeight: 1.5, color: 'var(--hz-muted)' }}>
              This runs in the background and may take a few minutes. You can refresh the page or come back later — the
              button stays disabled until the PR is ready. If generation fails, you can try again after a short wait.
            </p>
          </div>
        </div>
      )}

      <div style={{ flex: 1, padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>

      {/* Cross-run improvement vs previous completed analysis on same repo */}
      {job.status === 'completed' && result?.crossrun_summary && job.analysis_type !== 'context' && (() => {
        const cr = result.crossrun_summary as CrossrunSummary
        const prevId = cr.previous_job_id
        const sd = cr.score_delta
        const deltaColor =
          sd == null ? 'var(--hz-muted)' : sd > 0 ? 'var(--hz-ok)' : sd < 0 ? 'var(--hz-crit)' : 'var(--hz-ink)'
        const miniStats = [
          { label: 'Resolved', value: cr.resolved_count ?? 0, accent: 'var(--hz-ok)' },
          { label: 'New', value: cr.new_count ?? 0, accent: 'var(--hz-warn)' },
          { label: 'Still open', value: cr.persisting_count ?? 0, accent: 'var(--hz-ink)' },
          { label: 'Score Δ', value: sd == null ? '—' : sd > 0 ? `+${sd}` : String(sd), accent: deltaColor, valueColor: deltaColor },
        ]
        return (
          <div
            style={{
              border: '1px solid var(--hz-rule)',
              borderRadius: 'var(--hz-lg)',
              overflow: 'hidden',
              background: 'var(--hz-bg2)',
            }}
          >
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--hz-rule)', display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
              <div>
                <h2 className="hz-h2" style={{ fontSize: '14px', margin: 0, color: 'var(--hz-ink)' }}>Since last analysis</h2>
                <p className="hz-sm" style={{ marginTop: '6px', marginBottom: 0, maxWidth: '42rem', lineHeight: 1.5 }}>
                  Compared to the previous completed run on this repository (same fingerprint heuristics). Re-run after merging
                  fixes to see resolved issues and score changes.
                </p>
              </div>
              {prevId && (
                <Link
                  href={`/analyses/${prevId}`}
                  className="hz-sm"
                  style={{ color: 'var(--hz-info)', fontWeight: 500, textDecoration: 'underline', textUnderlineOffset: '3px', flexShrink: 0 }}
                >
                  Open previous analysis
                </Link>
              )}
            </div>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-px" style={{ background: 'var(--hz-rule)' }}>
              {miniStats.map((s, i) => (
                <div
                  key={i}
                  style={{
                    padding: '12px 14px',
                    position: 'relative',
                    overflow: 'hidden',
                    background: 'var(--hz-bg)',
                    textAlign: 'center',
                  }}
                >
                  <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: s.accent }} />
                  <div className="hz-grid-bg" style={{ position: 'absolute', inset: 0, opacity: 0.45, pointerEvents: 'none' }} />
                  <div style={{ fontSize: '22px', fontWeight: 700, letterSpacing: '-0.03em', color: (s as { valueColor?: string }).valueColor ?? 'var(--hz-ink)', fontVariantNumeric: 'tabular-nums', position: 'relative' }}>
                    {s.value}
                  </div>
                  <div style={{ fontSize: '9px', letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--hz-muted)', marginTop: '4px', position: 'relative' }}>
                    {s.label}
                  </div>
                </div>
              ))}
            </div>
            {Array.isArray(cr.resolved) && cr.resolved.length > 0 && (
              <details style={{ padding: '12px 18px', fontSize: '13px', color: 'var(--hz-ink2)' }}>
                <summary style={{ cursor: 'pointer', fontWeight: 500, color: 'var(--hz-ink)' }}>
                  Resolved findings ({cr.resolved.length})
                </summary>
                <ul style={{ marginTop: '10px', paddingLeft: '18px', maxHeight: '12rem', overflowY: 'auto', lineHeight: 1.5 }}>
                  {cr.resolved.map((r, i) => (
                    <li key={`${r.fingerprint ?? i}-${i}`}>
                      <span style={{ fontWeight: 500 }}>{(r.title ?? '').slice(0, 120)}</span>
                      {r.file_path && (
                        <span className="hz-tok hz-sm" style={{ marginLeft: '4px' }}>
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

      {/* Scores — mini stat bar pattern */}
      {result && (() => {
        const allFindings = (result.findings ?? []) as unknown as Finding[]
        const scorePillars: { label: string; score: number | null; pillar?: string; accent: string }[] = [
          { label: 'Global', score: result.score_global, pillar: undefined, accent: 'var(--hz-ink)' },
          { label: 'Metrics', score: result.score_metrics, pillar: 'metrics', accent: 'var(--hz-info)' },
          { label: 'Logs', score: result.score_logs, pillar: 'logs', accent: 'var(--hz-ok)' },
          { label: 'Traces', score: result.score_traces, pillar: 'traces', accent: 'var(--hz-warn)' },
        ]
        return (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px" style={{ background: 'var(--hz-rule)', borderBottom: '1px solid var(--hz-rule)' }}>
            {scorePillars.map(({ label, score, pillar, accent }) => {
              const counts = countBySeverity(allFindings, pillar)
              const justify = scoreJustification(score, allFindings, pillar)
              const isZero = score === 0
              const grade = score != null ? getScoreGrade(score) : null
              return (
                <div
                  key={label}
                  style={{
                    padding: '14px 16px',
                    position: 'relative',
                    overflow: 'hidden',
                    background: 'var(--hz-bg)',
                    textAlign: 'center',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px',
                  }}
                >
                  <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: accent }} />
                  <div className="hz-grid-bg" style={{ position: 'absolute', inset: 0, opacity: 0.5, pointerEvents: 'none' }} />
                  <div style={{ fontSize: '9px', letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--hz-muted)', position: 'relative' }}>
                    {label}
                  </div>
                  <div
                    style={{
                      fontSize: '32px',
                      fontWeight: 700,
                      letterSpacing: '-0.04em',
                      color: score != null ? hzGradeColorVar(getScoreGrade(score)) : 'var(--hz-muted)',
                      lineHeight: 1,
                      position: 'relative',
                    }}
                  >
                    {score ?? '—'}
                  </div>
                  {score != null && (
                    <div className="hz-sm" style={{ color: 'var(--hz-muted)', position: 'relative' }}>
                      ({grade})
                    </div>
                  )}
                  <div
                    style={{
                      marginTop: '6px',
                      borderRadius: 'var(--hz-sm)',
                      padding: '6px 8px',
                      fontSize: '11px',
                      lineHeight: 1.45,
                      textAlign: 'left',
                      background: isZero ? 'var(--hz-crit-bg)' : 'var(--hz-bg2)',
                      color: isZero ? 'var(--hz-crit)' : 'var(--hz-muted)',
                      border: `1px solid ${isZero ? 'var(--hz-crit-bd)' : 'var(--hz-rule)'}`,
                      position: 'relative',
                    }}
                  >
                    {justify}
                  </div>
                  {counts.total > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: '4px', marginTop: '4px', position: 'relative' }}>
                      {counts.critical > 0 && (
                        <span className="hz-badge hz-badge-crit" style={{ fontSize: '9px', padding: '2px 6px' }}>
                          <span className="hz-dot" />
                          {counts.critical} critical
                        </span>
                      )}
                      {counts.warning > 0 && (
                        <span className="hz-badge hz-badge-warn" style={{ fontSize: '9px', padding: '2px 6px' }}>
                          <span className="hz-dot" />
                          {counts.warning} warning
                        </span>
                      )}
                      {counts.info > 0 && (
                        <span className="hz-badge hz-badge-info" style={{ fontSize: '9px', padding: '2px 6px' }}>
                          <span className="hz-dot" />
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
        <details
          className="group"
          style={{
            border: '1px solid var(--hz-rule)',
            borderRadius: 'var(--hz-lg)',
            overflow: 'hidden',
          }}
        >
          <summary
            className="flex items-center gap-2 px-4 py-3 cursor-pointer select-none hz-label"
            style={{
              background: 'var(--hz-bg2)',
              color: 'var(--hz-muted)',
              letterSpacing: '0.1em',
            }}
          >
            <svg className="w-3.5 h-3.5 transition-transform group-open:rotate-90 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} style={{ color: 'var(--hz-muted)' }}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            Scoring reference
          </summary>
          <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)' }}>
                {['Grade', 'Range', 'Meaning', 'Score impact'].map((h) => (
                  <th
                    key={h}
                    className="hz-label"
                    style={{
                      textAlign: 'left',
                      padding: '8px 12px',
                      color: 'var(--hz-muted)',
                      fontWeight: 400,
                      letterSpacing: '0.1em',
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                { grade: 'A', range: '90–100', c: 'var(--hz-ok)', meaning: 'Excellent — production-ready observability', impact: 'No critical or warning findings' },
                { grade: 'B', range: '75–89', c: 'var(--hz-info)', meaning: 'Good coverage with minor gaps', impact: '–10 per warning, –3 per info' },
                { grade: 'C', range: '60–74', c: 'var(--hz-warn)', meaning: 'Partial — key signals missing or noisy', impact: 'Multiple warnings or 1–2 critical' },
                { grade: 'D', range: '0–59', c: 'var(--hz-crit)', meaning: 'Poor — high production risk', impact: '–25 per critical finding' },
              ].map(({ grade, range, c, meaning, impact }) => (
                <tr key={grade} style={{ borderBottom: '1px solid var(--hz-rule)', color: 'var(--hz-ink2)' }}>
                  <td style={{ padding: '8px 12px', fontWeight: 700, color: c }}>{grade}</td>
                  <td style={{ padding: '8px 12px', fontVariantNumeric: 'tabular-nums', color: 'var(--hz-muted)' }}>{range}</td>
                  <td style={{ padding: '8px 12px' }}>{meaning}</td>
                  <td style={{ padding: '8px 12px', color: 'var(--hz-muted)' }}>{impact}</td>
                </tr>
              ))}
              <tr style={{ background: 'var(--hz-bg2)', color: 'var(--hz-muted)' }}>
                <td style={{ padding: '8px 12px', fontWeight: 700, color: 'var(--hz-crit)' }}>0</td>
                <td style={{ padding: '8px 12px', fontVariantNumeric: 'tabular-nums' }}>—</td>
                <td style={{ padding: '8px 12px' }}>No instrumentation detected</td>
                <td style={{ padding: '8px 12px' }}>Metrics & traces require an SDK or agent</td>
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
          findings={result.findings as unknown as Finding[]}
          jobId={id}
          severityFilter={severityFilter}
          setSeverityFilter={setSeverityFilter}
          pillarFilter={pillarFilter}
          setPillarFilter={setPillarFilter}
        />
      )}

      {(job.status === 'running' || job.status === 'pending') && (
        <div
          role="status"
          aria-live="polite"
          style={{
            border: '1px solid var(--hz-rule)',
            borderRadius: 'var(--hz-lg)',
            padding: '20px',
            background: 'var(--hz-info-bg)',
            color: 'var(--hz-info)',
            textAlign: 'left',
          }}
        >
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <h2 className="hz-h2" style={{ fontSize: '16px', margin: 0, color: 'var(--hz-ink)' }}>
                {streamError ? 'Analysis in progress (live stream unavailable)' : 'Analysis in progress'}
              </h2>
              <p className="hz-body" style={{ marginTop: '6px', marginBottom: 0, fontSize: '13px', color: 'var(--hz-muted)' }}>
                {latestProgress?.message ??
                  (streaming ? 'Connecting to live progress…' : 'Waiting for the analysis worker…')}
              </p>
            </div>
            <div className="tabular-nums shrink-0 hz-body" style={{ fontSize: '13px', fontWeight: 500, color: 'var(--hz-ink2)' }}>
              {latestProgress != null ? `${Math.min(100, Math.max(0, latestProgress.progress_pct))}%` : '—'}
            </div>
          </div>
          <div style={{ height: '6px', background: 'var(--hz-rule)', borderRadius: '4px', overflow: 'hidden', marginBottom: '16px' }}>
            <div
              style={{
                height: '100%',
                borderRadius: '4px',
                background: 'var(--hz-info)',
                transition: 'width 0.3s ease-out',
                width: `${Math.min(100, Math.max(0, latestProgress?.progress_pct ?? 0))}%`,
              }}
            />
          </div>
          {(progressEvents.length > 0 || streaming) && (
            <AnalysisPipeline events={progressEvents} />
          )}
          {streamError && (
            <p className="hz-sm" style={{ color: 'var(--hz-warn)', marginBottom: '12px' }}>
              Could not open live stream ({streamError}). Status still refreshes about every 12s until complete.
            </p>
          )}
          <div
            style={{
              maxHeight: '13rem',
              overflowY: 'auto',
              paddingTop: '12px',
              borderTop: '1px solid var(--hz-rule)',
            }}
          >
            {progressEvents.length === 0 ? (
              <p className="hz-body" style={{ fontStyle: 'italic', color: 'var(--hz-muted)' }}>
                {streaming ? 'Connecting…' : 'No step updates yet.'}
              </p>
            ) : (
              progressEvents.map((e, i) => (
                <div
                  key={`${e.timestamp ?? ''}-${i}-${e.message.slice(0, 24)}`}
                  className="flex gap-2"
                  style={{
                    fontSize: '13px',
                    marginBottom: '6px',
                    fontWeight: i === progressEvents.length - 1 ? 500 : 400,
                    opacity: e.event_type === 'llm' ? 0.95 : 1,
                  }}
                >
                  <span
                    className="shrink-0 uppercase"
                    style={{
                      width: '5.5rem',
                      fontSize: '10px',
                      letterSpacing: '0.08em',
                      color: e.event_type === 'llm' ? 'var(--hz-warn)' : 'var(--hz-info)',
                    }}
                  >
                    {e.event_type === 'llm' ? `llm · ${e.llm_phase ?? '…'}` : e.stage}
                  </span>
                  <span style={{ minWidth: 0, color: 'var(--hz-ink2)' }}>
                    {e.message}
                    {e.event_type === 'llm' && e.model != null && (
                      <span className="hz-sm block mt-0.5" style={{ color: 'var(--hz-muted)' }}>
                        {e.model}
                        {e.input_tokens != null && e.output_tokens != null && (
                          <> · {e.input_tokens}↓ {e.output_tokens}↑ tok</>
                        )}
                        {e.latency_ms != null && <> · {Math.round(e.latency_ms)} ms</>}
                      </span>
                    )}
                  </span>
                </div>
              ))
            )}
          </div>
          <p className="hz-sm mt-4 mb-0" style={{ color: 'var(--hz-muted)' }}>
            Results will appear below when the analysis completes.
          </p>
        </div>
      )}

      {job.status === 'completed' && !result && (
        <div
          style={{
            padding: '16px',
            borderRadius: 'var(--hz-lg)',
            border: '1px solid var(--hz-warn-bd)',
            background: 'var(--hz-warn-bg)',
            color: 'var(--hz-warn)',
            fontSize: '13px',
          }}
        >
          No scores or findings were returned for this run. If this is an older analysis, run a new one;
          otherwise check API/worker logs for save errors.
        </div>
      )}
      </div>
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

  const sevActiveStyle = (value: string, active: boolean): CSSProperties => {
    if (!active) {
      return {
        padding: '4px 10px',
        borderRadius: '9999px',
        fontSize: '11px',
        fontWeight: 500,
        border: '1px solid var(--hz-rule)',
        background: 'var(--hz-bg3)',
        color: 'var(--hz-muted)',
        cursor: 'pointer',
      }
    }
    const map: Record<string, { bg: string; fg: string }> = {
      all: { bg: 'var(--hz-ink)', fg: 'var(--hz-bg)' },
      critical: { bg: 'var(--hz-crit)', fg: 'var(--hz-bg)' },
      warning: { bg: 'var(--hz-warn)', fg: 'var(--hz-bg)' },
      info: { bg: 'var(--hz-info)', fg: 'var(--hz-bg)' },
    }
    const m = map[value] ?? map.all
    return {
      padding: '4px 10px',
      borderRadius: '9999px',
      fontSize: '11px',
      fontWeight: 500,
      border: '1px solid transparent',
      background: m.bg,
      color: m.fg,
      cursor: 'pointer',
    }
  }

  const pillarActiveStyle = (value: string, active: boolean): CSSProperties => {
    if (!active) {
      return {
        padding: '4px 10px',
        borderRadius: '9999px',
        fontSize: '11px',
        fontWeight: 500,
        border: '1px solid var(--hz-rule)',
        background: 'var(--hz-bg3)',
        color: 'var(--hz-muted)',
        cursor: 'pointer',
      }
    }
    const map: Record<string, { bg: string; fg: string }> = {
      all: { bg: 'var(--hz-ink)', fg: 'var(--hz-bg)' },
      metrics: { bg: 'var(--hz-info)', fg: 'var(--hz-bg)' },
      logs: { bg: 'var(--hz-ok)', fg: 'var(--hz-bg)' },
      traces: { bg: 'var(--hz-warn)', fg: 'var(--hz-bg)' },
      iac: { bg: 'var(--hz-crit)', fg: 'var(--hz-bg)' },
      pipeline: { bg: 'var(--hz-ink2)', fg: 'var(--hz-bg)' },
    }
    const m = map[value] ?? map.all
    return {
      padding: '4px 10px',
      borderRadius: '9999px',
      fontSize: '11px',
      fontWeight: 500,
      border: '1px solid transparent',
      background: m.bg,
      color: m.fg,
      cursor: 'pointer',
    }
  }

  return (
    <div
      style={{
        borderRadius: 'var(--hz-lg)',
        border: '1px solid var(--hz-rule)',
        overflow: 'hidden',
        background: 'var(--hz-bg)',
      }}
    >
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="hz-h2" style={{ fontSize: '14px', margin: 0, color: 'var(--hz-ink)' }}>
            Findings
            <span className="hz-sm" style={{ marginLeft: '8px', fontWeight: 400, color: 'var(--hz-muted)' }}>
              {isFiltered ? `${filtered.length} of ${findings.length}` : findings.length}
            </span>
          </h2>
          <div className="flex items-center gap-3 flex-wrap">
            {hasNewInfo && (
              <span className="hz-sm" style={{ color: 'var(--hz-muted)' }}>
                <span style={{ color: 'var(--hz-ok)', fontWeight: 500 }}>{newCount} new</span>
                {' · '}
                <span>{persistingCount} persisting</span>
              </span>
            )}
            {isFiltered && (
              <button
                type="button"
                onClick={() => { setSeverityFilter('all'); setPillarFilter('all') }}
                className="hz-sm"
                style={{ color: 'var(--hz-muted)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', textUnderlineOffset: '3px' }}
              >
                Clear filters
              </button>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-4 items-end">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="hz-label shrink-0" style={{ color: 'var(--hz-muted)' }}>Priority</span>
            <div className="flex gap-1 flex-wrap">
              {availableSeverities.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setSeverityFilter(value)}
                  style={sevActiveStyle(value, severityFilter === value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="hidden sm:block w-px self-stretch min-h-[20px]" style={{ background: 'var(--hz-rule)' }} />

          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="hz-label shrink-0" style={{ color: 'var(--hz-muted)' }}>Signal</span>
            <div className="flex gap-1 flex-wrap">
              {availablePillars.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setPillarFilter(value)}
                  style={pillarActiveStyle(value, pillarFilter === value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {filtered.length > 0 ? (
        <div>
          {filtered.map((f, i) => (
            <div
              key={stableFindingKey(f, i, jobId)}
              style={{ borderTop: i === 0 ? undefined : '1px solid var(--hz-rule)' }}
            >
              <FindingCard finding={f} jobId={jobId} />
            </div>
          ))}
        </div>
      ) : (
        <div className="py-12 text-center hz-body" style={{ color: 'var(--hz-muted)' }}>
          No findings match the selected filters.
          <button
            type="button"
            onClick={() => { setSeverityFilter('all'); setPillarFilter('all') }}
            className="ml-1.5 underline underline-offset-2"
            style={{ color: 'var(--hz-ink)', background: 'none', border: 'none', cursor: 'pointer' }}
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
  signals: { value: FeedbackSignal; icon: React.ReactNode; title: string; tone: 'ok' | 'crit' | 'info' }[]
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

  const toneStyle = (tone: 'ok' | 'crit' | 'info', isActive: boolean): CSSProperties => {
    if (isActive) {
      if (tone === 'ok') return { background: 'var(--hz-ok-bg)', color: 'var(--hz-ok)' }
      if (tone === 'crit') return { background: 'var(--hz-crit-bg)', color: 'var(--hz-crit)' }
      return { background: 'var(--hz-info-bg)', color: 'var(--hz-info)' }
    }
    return { background: 'transparent', color: 'var(--hz-muted)' }
  }

  return (
    <div className="flex items-center gap-1.5">
      <span className="hz-sm select-none" style={{ color: 'var(--hz-muted)' }}>{label}</span>
      {signals.map((s) => (
        <button
          key={s.value}
          type="button"
          onClick={() => handle(s.value)}
          disabled={busy || active !== null}
          title={s.title}
          className="p-1 rounded-md disabled:cursor-not-allowed disabled:opacity-40"
          style={{
            ...toneStyle(s.tone, active === s.value),
            border: '1px solid transparent',
          }}
          onMouseEnter={(e) => {
            if (active || busy) return
            e.currentTarget.style.color =
              s.tone === 'ok' ? 'var(--hz-ok)' : s.tone === 'crit' ? 'var(--hz-crit)' : 'var(--hz-info)'
          }}
          onMouseLeave={(e) => {
            if (active === s.value) return
            e.currentTarget.style.color = 'var(--hz-muted)'
            e.currentTarget.style.background = 'transparent'
          }}
        >
          {s.icon}
        </button>
      ))}
      {active && (
        <span className="hz-sm italic" style={{ color: 'var(--hz-muted)' }}>
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
  const sev = hzSeverityTokens(finding.severity)
  return (
    <div style={{ padding: '16px' }}>
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 shrink-0 rounded font-medium"
          style={{
            padding: '2px 8px',
            fontSize: '11px',
            background: sev.bg,
            color: sev.color,
            border: sev.border,
          }}
        >
          {finding.severity}
        </span>

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-3 mb-1">
            <div className="flex items-center flex-wrap gap-2 min-w-0">
              <span className="font-medium text-sm" style={{ color: 'var(--hz-ink)' }}>{finding.title}</span>
              {(finding.crossrun_status === 'new' || (finding.crossrun_status == null && finding.is_new === true)) && (
                <span
                  className="text-xs font-medium rounded shrink-0"
                  style={{ padding: '2px 6px', background: 'var(--hz-ok-bg)', color: 'var(--hz-ok)', border: '1px solid var(--hz-ok-bd)' }}
                >
                  New
                </span>
              )}
              {finding.crossrun_status === 'persisting' && (
                <span
                  className="text-xs font-medium rounded shrink-0"
                  style={{ padding: '2px 6px', background: 'var(--hz-warn-bg)', color: 'var(--hz-warn)', border: '1px solid var(--hz-warn-bd)' }}
                >
                  Still open
                </span>
              )}
              <span
                className="text-xs rounded shrink-0"
                style={{ padding: '2px 6px', background: 'var(--hz-bg3)', color: 'var(--hz-muted)', border: '1px solid var(--hz-rule)' }}
              >
                {finding.pillar}
              </span>
              {(finding.estimated_monthly_cost_impact ?? 0) > 0 && (
                <span className="text-xs font-medium shrink-0" style={{ color: 'var(--hz-warn)' }}>
                  ~${finding.estimated_monthly_cost_impact}/mo
                </span>
              )}
            </div>

            {isValidFindingId(finding.id) && (
              <div className="shrink-0">
                <FeedbackRow
                  label="Accurate?"
                  findingId={finding.id!}
                  jobId={jobId}
                  targetType="finding"
                  signals={[
                    { value: 'thumbs_up', icon: <ThumbUpIcon />, title: 'Accurate finding — true positive', tone: 'ok' },
                    { value: 'thumbs_down', icon: <ThumbDownIcon />, title: 'False positive — not a real issue', tone: 'crit' },
                  ]}
                />
              </div>
            )}
          </div>

          <p className="hz-body" style={{ fontSize: '13px', marginBottom: 0 }}>{finding.description}</p>

          {finding.file_path && (
            <span className="hz-tok hz-sm mt-1 block">
              {finding.file_path}:{finding.line_start}
            </span>
          )}

          {(finding.suggestion || finding.code_before || finding.code_after) && (
            <div className="mt-3 rounded-lg overflow-hidden" style={{ border: '1px solid var(--hz-rule)' }}>
              <details>
                <summary
                  className="flex items-center justify-between px-3 py-2 cursor-pointer select-none group"
                  style={{ background: 'var(--hz-bg2)' }}
                >
                  <span className="text-xs font-medium flex items-center gap-1.5" style={{ color: 'var(--hz-ink2)' }}>
                    <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                    </svg>
                    {suggestedFixIsNoOp(finding) ? 'View code (no change — current matches suggested)' : 'View suggested fix'}
                  </span>
                  <svg className="w-3.5 h-3.5 transition-transform group-open:rotate-180 shrink-0" style={{ color: 'var(--hz-muted)' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </summary>

                <div className="hz-term hz-scanline" style={{ background: 'var(--hz-bg4)' }}>
                  <SuggestedFixDiff finding={finding} />
                </div>

                {isValidFindingId(finding.id) && (
                  <div
                    className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
                    style={{ borderTop: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)' }}
                  >
                    <FeedbackRow
                      label="Was this fix helpful?"
                      findingId={finding.id!}
                      jobId={jobId}
                      targetType="suggestion"
                      signals={[
                        { value: 'thumbs_up', icon: <ThumbUpIcon />, title: 'Helpful and correct fix', tone: 'ok' },
                        { value: 'thumbs_down', icon: <ThumbDownIcon />, title: 'Incorrect or unhelpful fix', tone: 'crit' },
                        { value: 'applied', icon: <CheckIcon />, title: 'Applied this fix to my code', tone: 'info' },
                      ]}
                    />
                    <span className="hz-sm italic hidden sm:block" style={{ color: 'var(--hz-muted)' }}>
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
