'use client'

import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { analysesApi, billingApi, reposApi } from '@/lib/api'
import { RepoWebLink } from '@/components/RepoWebLink'
import { HzStatusBadge } from '@/components/HzStatusBadge'
import { formatRelativeTime } from '@/lib/utils'
import Link from 'next/link'

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

function gradeBg(g: 'A' | 'B' | 'C' | 'D'): string {
  if (g === 'A') return 'var(--hz-ok-bg)'
  if (g === 'B') return 'var(--hz-info-bg)'
  if (g === 'C') return 'var(--hz-warn-bg)'
  return 'var(--hz-crit-bg)'
}

export default function DashboardPage() {
  const router = useRouter()

  const { data: analysesList } = useQuery({
    queryKey: ['analyses', 'recent'],
    queryFn: () => analysesApi.list({ limit: 10 }),
  })
  const analyses = analysesList?.items

  const { data: usage } = useQuery({
    queryKey: ['billing-usage'],
    queryFn: billingApi.usage,
  })

  const { data: repos } = useQuery({
    queryKey: ['repositories'],
    queryFn: reposApi.list,
  })

  const completedAnalyses = analyses?.filter((a) => a.status === 'completed') ?? []
  const avgScore = completedAnalyses.length
    ? Math.round(completedAnalyses.reduce((s, a) => s + (a.score_global || 0), 0) / completedAnalyses.length)
    : null

  const avgGrade = avgScore ? gradeFromScore(avgScore) : null
  const creditPct = usage ? Math.round((usage.credits_used / usage.credits_included) * 100) : 0
  const fixPrCount = analyses?.filter((a) => a.fix_pr_url).length ?? 0

  const stats = [
    {
      label: 'Global score',
      value: avgScore ?? '—',
      sub: avgGrade ? `grade ${avgGrade} · recent avg` : 'no data yet',
      accent: avgGrade ? gradeColor(avgGrade) : 'var(--hz-rule2)',
      valueColor: avgGrade ? gradeColor(avgGrade) : undefined,
    },
    {
      label: 'Analyses',
      value: completedAnalyses.length,
      sub: 'completed · recent',
      accent: 'var(--hz-info)',
    },
    {
      label: 'Repositories',
      value: repos?.length ?? 0,
      sub: 'active',
      accent: 'var(--hz-ok)',
    },
    {
      label: 'Credits used',
      value: usage?.credits_used ?? 0,
      sub: `of ${usage?.credits_included ?? 0} included`,
      accent: creditPct > 80 ? 'var(--hz-warn)' : 'var(--hz-ok)',
      bar: { pct: creditPct, color: creditPct > 80 ? 'var(--hz-warn)' : 'var(--hz-ok)' },
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--hz-bg)' }}>

      {/* ── Topbar ── */}
      <div style={{
        padding: '18px 24px 16px',
        borderBottom: '1px solid var(--hz-rule)',
      }}>
        <div style={{ fontSize: '22px', fontWeight: 700, letterSpacing: '-0.035em', color: 'var(--hz-ink)', lineHeight: 1 }}>
          Dashboard
        </div>
        <div style={{ fontSize: '12px', color: 'var(--hz-muted)', marginTop: '5px' }}>
          Overview of your observability health
        </div>
      </div>

      {/* ── KPI Stats Bar (responsive grid; 1px gaps use --hz-rule) ── */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px"
        style={{ borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-rule)' }}
      >
        {stats.map((s, i) => (
          <div
            key={i}
            style={{
              padding: '16px 20px',
              position: 'relative',
              overflow: 'hidden',
              background: 'var(--hz-bg)',
            }}
          >
            {/* accent line */}
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: s.accent }} />
            {/* grid bg */}
            <div className="hz-grid-bg" style={{ position: 'absolute', inset: 0, opacity: 0.5, pointerEvents: 'none' }} />

            <div style={{ fontSize: '9px', letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--hz-muted)', marginBottom: '6px', position: 'relative' }}>
              {s.label}
            </div>
            <div style={{ fontSize: '24px', fontWeight: 700, letterSpacing: '-0.04em', color: (s as { valueColor?: string }).valueColor ?? 'var(--hz-ink)', lineHeight: 1, position: 'relative' }}>
              {s.value}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--hz-muted)', marginTop: '4px', position: 'relative' }}>
              {s.sub}
            </div>
            {(s as { bar?: { pct: number; color: string } }).bar && (
              <div style={{ marginTop: '8px', height: '3px', background: 'var(--hz-rule)', borderRadius: '2px', overflow: 'hidden', position: 'relative' }}>
                <div style={{
                  height: '100%', borderRadius: '2px',
                  width: `${Math.min(100, (s as { bar: { pct: number; color: string } }).bar.pct)}%`,
                  background: (s as { bar: { pct: number; color: string } }).bar.color,
                  transition: 'width 0.6s cubic-bezier(0.4,0,0.2,1)',
                }} />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ── Recent Analyses ── */}
      <div style={{ flex: 1, padding: '24px', overflow: 'auto' }}>
        <div style={{
          border: '1px solid var(--hz-rule)',
          borderRadius: 'var(--hz-lg)',
          overflow: 'hidden',
          background: 'var(--hz-bg)',
        }}>
          {/* header */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '14px 18px', borderBottom: '1px solid var(--hz-rule)',
            background: 'var(--hz-bg2)',
          }}>
            <span style={{ fontSize: '12px', fontWeight: 500, color: 'var(--hz-ink)', letterSpacing: '-0.01em' }}>
              Recent Analyses
            </span>
            <Link
              href="/analyses"
              style={{ fontSize: '11px', color: 'var(--hz-muted)', textDecoration: 'none' }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--hz-ink)' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--hz-muted)' }}
            >
              view all →
            </Link>
          </div>

          {/* rows */}
          {(!analyses || analyses.length === 0) && (
            <div style={{ padding: '32px', textAlign: 'center', fontSize: '12px', color: 'var(--hz-muted)' }}>
              No analyses yet. Connect a repository to get started.
            </div>
          )}
          {analyses?.map((job) => {
            const g = job.score_global != null ? gradeFromScore(job.score_global) : null
            const repoName = job.repo_full_name?.split('/')[1] ?? job.repo_id.slice(0, 8)
            const owner = job.repo_full_name?.split('/')[0] ?? '?'

            return (
              <div
                key={job.id}
                role="button"
                tabIndex={0}
                onClick={() => router.push(`/analyses/${job.id}`)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); router.push(`/analyses/${job.id}`) } }}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '10px 18px', borderBottom: '1px solid var(--hz-rule)', cursor: 'pointer',
                }}
                onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--hz-bg2)' }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent' }}
              >
                {/* left: repo info */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
                  <div style={{
                    width: '16px', height: '16px', borderRadius: '50%',
                    background: 'var(--hz-bg4)', flexShrink: 0,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '9px', fontWeight: 700, color: 'var(--hz-ink2)',
                  }}>
                    {owner[0]?.toUpperCase() ?? '?'}
                  </div>
                  <div>
                    <div style={{ fontSize: '12px', fontWeight: 500, color: 'var(--hz-ink)' }}>
                      {job.repo_web_url && job.repo_full_name
                        ? <RepoWebLink name={repoName} href={job.repo_web_url} />
                        : repoName}
                    </div>
                    <div style={{ fontSize: '10px', color: 'var(--hz-muted)' }}>
                      {job.branch_ref ?? job.trigger} · {formatRelativeTime(job.created_at)}
                    </div>
                  </div>
                </div>

                {/* right: status + score */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
                  <HzStatusBadge status={job.status} />
                  {job.score_global != null && g && (
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '14px', fontWeight: 700, color: gradeColor(g), letterSpacing: '-0.03em' }}>
                        {job.score_global}
                      </div>
                      <div style={{ fontSize: '10px', padding: '0px 5px', borderRadius: '3px', background: gradeBg(g), color: gradeColor(g), textAlign: 'center' }}>
                        {g}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
