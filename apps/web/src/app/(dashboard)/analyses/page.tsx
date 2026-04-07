'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { analysesApi, reposApi, type AnalysisJob, type AnalysisListParams } from '@/lib/api'
import { HzStatusBadge } from '@/components/HzStatusBadge'
import { ScmLogo } from '@/components/ScmLogo'
import { formatRelativeTime } from '@/lib/utils'

const PAGE_SIZES = [10, 20, 50] as const

// Grade derived from score — A=ok / B=info / C=warn / D=crit
function gradeFromScore(s: number): 'A' | 'B' | 'C' | 'D' {
  if (s >= 90) return 'A'
  if (s >= 75) return 'B'
  if (s >= 55) return 'C'
  return 'D'
}

function gradeColor(g: 'A' | 'B' | 'C' | 'D'): string {
  if (g === 'A') return 'var(--hz-ok)'
  if (g === 'B') return 'var(--hz-info)'
  if (g === 'C') return 'var(--hz-warn)'
  return 'var(--hz-crit)'
}

function scoreBg(g: 'A' | 'B' | 'C' | 'D'): string {
  if (g === 'A') return 'var(--hz-ok-bg)'
  if (g === 'B') return 'var(--hz-info-bg)'
  if (g === 'C') return 'var(--hz-warn-bg)'
  return 'var(--hz-crit-bg)'
}

// Minimal 5-bar sparkline using inline styles
function Sparkline({ score, grade }: { score: number | null; grade: 'A' | 'B' | 'C' | 'D' | null }) {
  if (!score || !grade) return <span style={{ color: 'var(--hz-muted)', fontSize: '10px' }}>—</span>
  const vals = [
    Math.max(10, score - 25 + 5),
    Math.max(10, score - 15 + 4),
    Math.max(10, score - 8 + 3),
    Math.max(10, score - 3 + 2),
    score,
  ]
  const max = Math.max(...vals)
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: '2px', height: '20px' }}>
      {vals.map((v, i) => (
        <div
          key={i}
          style={{
            width: '4px',
            height: `${Math.round((v / max) * 20)}px`,
            borderRadius: '1px',
            background: i === 4 ? gradeColor(grade) : 'var(--hz-rule2)',
          }}
        />
      ))}
    </div>
  )
}

export default function AnalysesPage() {
  const router = useRouter()
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(20)
  const [sort, setSort] = useState<string>('created_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [qInput, setQInput] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [status, setStatus] = useState('')
  const [trigger, setTrigger] = useState('')
  const [analysisType, setAnalysisType] = useState('')
  const [repoId, setRepoId] = useState('')
  const [fixPr, setFixPr] = useState<'' | 'has_pr' | 'generating' | 'can_suggest'>('')

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(qInput.trim()), 350)
    return () => clearTimeout(t)
  }, [qInput])

  useEffect(() => { setPage(0) }, [debouncedQ, status, trigger, analysisType, repoId, fixPr, pageSize])

  const listParams: AnalysisListParams = useMemo(() => ({
    limit: pageSize,
    offset: page * pageSize,
    sort,
    order,
    q: debouncedQ || undefined,
    status: status || undefined,
    trigger: trigger || undefined,
    analysis_type: analysisType || undefined,
    repo_id: repoId || undefined,
    fix_pr: fixPr || undefined,
  }), [page, pageSize, sort, order, debouncedQ, status, trigger, analysisType, repoId, fixPr])

  const { data, isLoading, isPlaceholderData } = useQuery({
    queryKey: ['analyses', 'list', listParams],
    queryFn: () => analysesApi.list(listParams),
    placeholderData: keepPreviousData,
  })

  const { data: repos } = useQuery({
    queryKey: ['repositories'],
    queryFn: reposApi.list,
  })

  const total = data?.total ?? 0
  const items = data?.items ?? []
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const pageStart = total === 0 ? 0 : page * pageSize + 1
  const pageEnd = Math.min(total, (page + 1) * pageSize)

  // Derived mini-stats from loaded page
  const completedItems = items.filter((j) => j.status === 'completed')
  const avgScore = completedItems.length
    ? Math.round(completedItems.reduce((s, j) => s + (j.score_global ?? 0), 0) / completedItems.length)
    : null
  const fixPrCount = items.filter((j) => j.fix_pr_url).length

  const toggleSort = useCallback((column: string) => {
    if (sort === column) {
      setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(column)
      setOrder(column === 'repo' || column === 'status' ? 'asc' : 'desc')
    }
  }, [sort])

  const hasFilters = !!(qInput || status || trigger || analysisType || repoId || fixPr)

  function clearFilters() {
    setQInput(''); setDebouncedQ(''); setStatus(''); setTrigger('')
    setAnalysisType(''); setRepoId(''); setFixPr(''); setSort('created_at'); setOrder('desc')
  }

  if (isLoading && !data) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px' }}>
        <span className="hz-cursor" style={{ opacity: 0.4 }} />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--hz-bg)' }}>

      {/* ── Topbar ── */}
      <div style={{
        padding: '18px 24px 16px',
        borderBottom: '1px solid var(--hz-rule)',
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: '22px', fontWeight: 700, letterSpacing: '-0.035em', color: 'var(--hz-ink)', lineHeight: 1 }}>
            Analyses
          </div>
          <div style={{ fontSize: '12px', color: 'var(--hz-muted)', marginTop: '5px' }}>
            History of all observability analyses
          </div>
        </div>
      </div>

      {/* ── Mini Stats Bar ── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        borderBottom: '1px solid var(--hz-rule)',
        background: 'var(--hz-bg)',
      }}>
        {[
          { label: 'Total analyses', value: total, sub: 'this period', accent: 'var(--hz-ok)' },
          {
            label: 'Avg score', value: avgScore ?? '—',
            sub: avgScore ? `grade ${gradeFromScore(avgScore)}` : 'no data',
            accent: avgScore ? gradeColor(gradeFromScore(avgScore)) : 'var(--hz-rule2)',
            valueColor: avgScore ? gradeColor(gradeFromScore(avgScore)) : undefined,
          },
          { label: 'On this page', value: completedItems.length, sub: 'completed', accent: 'var(--hz-info)' },
          { label: 'Fix PRs', value: fixPrCount, sub: 'on this page', accent: 'var(--hz-ok)' },
        ].map((s, i) => (
          <div
            key={i}
            style={{
              padding: '12px 20px',
              borderRight: i < 3 ? '1px solid var(--hz-rule)' : 'none',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            {/* accent line */}
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: s.accent }} />
            {/* grid bg */}
            <div className="hz-grid-bg" style={{ position: 'absolute', inset: 0, opacity: 0.5, pointerEvents: 'none' }} />
            <div style={{ fontSize: '9px', letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--hz-muted)', marginBottom: '4px', position: 'relative' }}>
              {s.label}
            </div>
            <div style={{ fontSize: '20px', fontWeight: 700, letterSpacing: '-0.04em', color: (s as { valueColor?: string }).valueColor ?? 'var(--hz-ink)', lineHeight: 1, position: 'relative' }}>
              {s.value}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--hz-muted)', marginTop: '3px', position: 'relative' }}>
              {s.sub}
            </div>
          </div>
        ))}
      </div>

      {/* ── Filters ── */}
      <div style={{
        padding: '12px 24px',
        borderBottom: '1px solid var(--hz-rule)',
        display: 'flex',
        alignItems: 'flex-end',
        gap: '10px',
        flexWrap: 'wrap',
        background: 'var(--hz-bg2)',
      }}>
        {/* Search */}
        <FilterGroup label="Search repo">
          <input
            type="search"
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="owner/name…"
            className="hz-inp"
            style={{ width: '140px', fontSize: '11px', padding: '5px 9px' }}
          />
        </FilterGroup>

        {/* Repository */}
        <FilterGroup label="Repository">
          <select value={repoId} onChange={(e) => setRepoId(e.target.value)}
            className="hz-inp" style={{ width: '120px', fontSize: '11px', padding: '5px 9px' }}>
            <option value="">All</option>
            {repos?.map((r) => <option key={r.id} value={r.id}>{r.full_name.split('/')[1]}</option>)}
          </select>
        </FilterGroup>

        {/* Status */}
        <FilterGroup label="Status">
          <select value={status} onChange={(e) => setStatus(e.target.value)}
            className="hz-inp" style={{ width: '100px', fontSize: '11px', padding: '5px 9px' }}>
            <option value="">All</option>
            <option value="pending">pending</option>
            <option value="running">running</option>
            <option value="completed">completed</option>
            <option value="failed">failed</option>
          </select>
        </FilterGroup>

        {/* Trigger */}
        <FilterGroup label="Trigger">
          <select value={trigger} onChange={(e) => setTrigger(e.target.value)}
            className="hz-inp" style={{ width: '100px', fontSize: '11px', padding: '5px 9px' }}>
            <option value="">All</option>
            <option value="pr">pr</option>
            <option value="push">push</option>
            <option value="manual">manual</option>
            <option value="scheduled">scheduled</option>
          </select>
        </FilterGroup>

        {/* Type */}
        <FilterGroup label="Type">
          <select value={analysisType} onChange={(e) => setAnalysisType(e.target.value)}
            className="hz-inp" style={{ width: '100px', fontSize: '11px', padding: '5px 9px' }}>
            <option value="">All</option>
            <option value="quick">quick</option>
            <option value="full">full</option>
            <option value="repository">repository</option>
          </select>
        </FilterGroup>

        {/* Fix PR */}
        <FilterGroup label="Fix PR">
          <select value={fixPr} onChange={(e) => setFixPr(e.target.value as typeof fixPr)}
            className="hz-inp" style={{ width: '110px', fontSize: '11px', padding: '5px 9px' }}>
            <option value="">All</option>
            <option value="has_pr">suggested</option>
            <option value="generating">generating</option>
            <option value="can_suggest">can suggest</option>
          </select>
        </FilterGroup>
      </div>

      {/* ── Results bar ── */}
      <div style={{
        padding: '8px 24px',
        borderBottom: '1px solid var(--hz-rule)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ fontSize: '11px', color: 'var(--hz-muted)' }}>
          <span style={{ color: 'var(--hz-ink)', fontWeight: 500 }}>{total}</span>
          {' '}result{total !== 1 ? 's' : ''}
          {isPlaceholderData && <span style={{ opacity: 0.6 }}> — updating…</span>}
        </div>
        {hasFilters && (
          <button
            type="button"
            onClick={clearFilters}
            style={{
              fontSize: '11px',
              color: 'var(--hz-muted)',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              textDecoration: 'underline',
              textUnderlineOffset: '3px',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--hz-ink)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--hz-muted)' }}
          >
            clear filters
          </button>
        )}
      </div>

      {/* ── Table ── */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '860px' }}>
          <thead>
            <tr>
              {[
                { label: 'Repo', col: 'repo', w: '220px' },
                { label: 'Trigger', col: 'trigger' },
                { label: 'Type', col: 'analysis_type' },
                { label: 'Status', col: 'status' },
                { label: 'Score', col: 'score_global' },
                { label: 'Trend', col: null },
                { label: 'Credits', col: 'credits_consumed' },
                { label: 'Fix PR', col: null },
                { label: 'Date ↓', col: 'created_at' },
              ].map(({ label, col, w }) => (
                <th
                  key={label}
                  style={{
                    padding: '8px 12px',
                    fontSize: '10px',
                    fontWeight: 400,
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    color: sort === col ? 'var(--hz-ink)' : 'var(--hz-muted)',
                    textAlign: 'left',
                    borderBottom: '1px solid var(--hz-rule)',
                    background: 'var(--hz-bg2)',
                    whiteSpace: 'nowrap',
                    cursor: col ? 'pointer' : 'default',
                    width: w,
                    userSelect: 'none',
                  }}
                  onClick={() => col && toggleSort(col)}
                  onMouseEnter={(e) => { if (col) e.currentTarget.style.color = 'var(--hz-ink)' }}
                  onMouseLeave={(e) => { if (col) e.currentTarget.style.color = sort === col ? 'var(--hz-ink)' : 'var(--hz-muted)' }}
                >
                  {label}{col && sort === col && (order === 'asc' ? ' ↑' : ' ↓')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={9} style={{ padding: '40px', textAlign: 'center', fontSize: '12px', color: 'var(--hz-muted)' }}>
                  No analyses match your filters.
                </td>
              </tr>
            )}
            {items.map((job, i) => {
              const g = job.score_global != null ? gradeFromScore(job.score_global) : null
              const repoName = job.repo_full_name?.split('/')[1] ?? job.repo_id.slice(0, 8)
              const owner = job.repo_full_name?.split('/')[0] ?? '?'

              return (
                <tr
                  key={job.id}
                  style={{
                    borderBottom: '1px solid var(--hz-rule)',
                    cursor: 'pointer',
                    animation: `hz-row-in 0.3s ease both`,
                    animationDelay: `${i * 0.02}s`,
                  }}
                  onClick={() => router.push(`/analyses/${job.id}`)}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--hz-bg2)' }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  {/* Repo — SCM logo + name */}
                  <td style={{ padding: '10px 12px', fontSize: '11px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span title={job.scm_type ?? 'scm'} style={{ display: 'flex', flexShrink: 0 }}>
                        <ScmLogo scm={job.scm_type} className="h-5 w-5" />
                      </span>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: '12px', color: 'var(--hz-ink)', fontWeight: 500 }}>
                          <span style={{ color: 'var(--hz-muted)', fontWeight: 400 }}>{owner}/</span>
                          {repoName}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--hz-muted)', marginTop: '1px' }}>
                          {job.branch_ref ?? '—'}
                          {job.commit_sha && ` · ${job.commit_sha.slice(0, 7)}`}
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* Trigger */}
                  <td style={{ padding: '10px 12px' }}>
                    <span style={{ fontSize: '10px', color: 'var(--hz-muted)' }}>{job.trigger}</span>
                  </td>

                  {/* Type */}
                  <td style={{ padding: '10px 12px' }}>
                    <span style={{
                      fontSize: '10px', color: 'var(--hz-muted)',
                      padding: '2px 6px', borderRadius: '3px',
                      background: 'var(--hz-bg3)', border: '1px solid var(--hz-rule)',
                    }}>
                      {job.analysis_type}
                    </span>
                  </td>

                  {/* Status */}
                  <td style={{ padding: '10px 12px' }}>
                    <HzStatusBadge status={job.status} />
                  </td>

                  {/* Score */}
                  <td style={{ padding: '10px 12px' }}>
                    {job.score_global != null && g ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        <div style={{ fontSize: '13px', fontWeight: 700, letterSpacing: '-0.03em', color: gradeColor(g), lineHeight: 1 }}>
                          {job.score_global}{' '}
                          <span style={{ fontSize: '10px', fontWeight: 400 }}>({g})</span>
                        </div>
                        {/* mini bar */}
                        <div style={{ width: '48px', height: '3px', borderRadius: '2px', background: 'var(--hz-rule)', overflow: 'hidden' }}>
                          <div style={{ height: '100%', borderRadius: '2px', width: `${job.score_global}%`, background: gradeColor(g), transition: 'width 0.6s cubic-bezier(0.4,0,0.2,1)' }} />
                        </div>
                        <ScoreDelta job={job} />
                      </div>
                    ) : (
                      <span style={{ color: 'var(--hz-muted)', fontSize: '11px' }}>—</span>
                    )}
                  </td>

                  {/* Trend sparkline */}
                  <td style={{ padding: '10px 12px' }}>
                    <Sparkline score={job.score_global} grade={g} />
                  </td>

                  {/* Credits */}
                  <td style={{ padding: '10px 12px' }}>
                    {job.credits_consumed != null && job.credits_consumed > 0 ? (
                      <div style={{
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        width: '20px', height: '20px', borderRadius: '4px',
                        background: 'var(--hz-bg3)', border: '1px solid var(--hz-rule)',
                        fontSize: '11px', fontWeight: 500, color: 'var(--hz-ink2)',
                      }}>
                        {job.credits_consumed}
                      </div>
                    ) : (
                      <span style={{ color: 'var(--hz-muted)', fontSize: '10px' }}>—</span>
                    )}
                  </td>

                  {/* Fix PR */}
                  <td style={{ padding: '10px 12px' }} onClick={(e) => e.stopPropagation()}>
                    <HzFixPrCell job={job} />
                  </td>

                  {/* Date */}
                  <td style={{ padding: '10px 12px', fontSize: '11px', color: 'var(--hz-muted)', whiteSpace: 'nowrap' }}>
                    {formatRelativeTime(job.created_at)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* ── Pagination ── */}
      <div style={{
        padding: '10px 24px',
        borderTop: '1px solid var(--hz-rule)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: 'var(--hz-bg)',
        flexWrap: 'wrap',
        gap: '8px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: 'var(--hz-muted)' }}>
          <span>Rows</span>
          <select
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0) }}
            style={{
              fontSize: '11px', padding: '4px 8px',
              border: '1px solid var(--hz-rule2)', borderRadius: '5px',
              background: 'var(--hz-bg)', color: 'var(--hz-ink)', outline: 'none',
            }}
          >
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--hz-muted)' }}>
          <PaginationBtn disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>← prev</PaginationBtn>
          <span style={{ padding: '0 8px' }}>{pageStart}–{pageEnd} of {total}</span>
          <PaginationBtn disabled={page >= totalPages - 1 || total === 0} onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}>next →</PaginationBtn>
        </div>
      </div>

      <style>{`
        @keyframes hz-row-in {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
      <div style={{ fontSize: '9px', color: 'var(--hz-muted)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
        {label}
      </div>
      {children}
    </div>
  )
}

function PaginationBtn({ disabled, onClick, children }: { disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      style={{
        fontSize: '11px', padding: '4px 10px',
        border: '1px solid var(--hz-rule2)', borderRadius: '5px',
        background: 'var(--hz-bg)', color: disabled ? 'var(--hz-muted)' : 'var(--hz-ink)',
        cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1,
      }}
    >
      {children}
    </button>
  )
}

function ScoreDelta({ job }: { job: AnalysisJob }) {
  const d = job.result?.crossrun_summary?.score_delta
  if (d == null || Number.isNaN(d)) return null
  const color = d > 0 ? 'var(--hz-ok)' : d < 0 ? 'var(--hz-crit)' : 'var(--hz-muted)'
  return (
    <div style={{ fontSize: '10px', color, display: 'flex', alignItems: 'center', gap: '2px' }}>
      {d > 0 ? '↑' : d < 0 ? '↓' : ''}{Math.abs(d)} vs prev
    </div>
  )
}

function HzFixPrCell({ job }: { job: AnalysisJob }) {
  if (job.fix_pr_url) {
    return (
      <a
        href={job.fix_pr_url}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: '4px',
          padding: '3px 8px', borderRadius: '4px', fontSize: '10px', fontWeight: 500,
          background: 'var(--hz-ok-bg)', color: 'var(--hz-ok)',
          border: '1px solid var(--hz-ok-bd)', textDecoration: 'none',
        }}
      >
        PR suggested
      </a>
    )
  }
  if (job.fix_pr_pending) {
    return (
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: '5px',
        padding: '3px 8px', borderRadius: '4px', fontSize: '10px', fontWeight: 500,
        background: 'var(--hz-info-bg)', color: 'var(--hz-info)',
      }}>
        <div style={{ width: '5px', height: '5px', borderRadius: '50%', background: 'var(--hz-info)', animation: 'hz-pulse 1s ease infinite' }} />
        Generating…
      </div>
    )
  }
  if (job.status === 'completed' && job.fix_pr_eligible) {
    return (
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: '4px',
        padding: '3px 8px', borderRadius: '4px', fontSize: '10px', fontWeight: 500,
        background: 'var(--hz-warn-bg)', color: 'var(--hz-warn)',
        border: '1px solid var(--hz-warn-bd)',
      }}>
        Can suggest PR
      </div>
    )
  }
  if (job.status === 'completed' && !job.fix_pr_eligible) {
    return <span style={{ color: 'var(--hz-muted)', fontSize: '10px' }}>No recommendations</span>
  }
  return <span style={{ color: 'var(--hz-muted)', fontSize: '10px' }}>—</span>
}
