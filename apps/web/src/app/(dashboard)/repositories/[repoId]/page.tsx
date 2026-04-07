'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { analysesApi, reposApi, type AnalysisJob, type Repository } from '@/lib/api'
import { ScmLogo } from '@/components/ScmLogo'
import { LanguageLogo } from '@/components/LanguageLogo'
import { ObsBackendLogo } from '@/components/ObsBackendLogo'
import { InstrumentationLogo, instrumentationLabel } from '@/components/InstrumentationLogo'
import { InstrumentationRecommendationCard } from '@/components/InstrumentationRecommendationCard'
import { getInstrumentationRecommendation } from '@/lib/instrumentation-recommendation'
import { formatDate, getScoreGrade, hzGradeColorVar } from '@/lib/utils'
import { HzStatusBadge } from '@/components/HzStatusBadge'

function ContextSection({ repo, latestAnalysis }: { repo: Repository; latestAnalysis?: import('@/lib/api').AnalysisJob | null }) {
  const meta = (repo.obs_metadata ?? {}) as Record<string, unknown>
  const tags = (meta.tags ?? meta.labels ?? {}) as Record<string, string>
  const recommendation = getInstrumentationRecommendation(repo, latestAnalysis)

  return (
    <div
      style={{
        border: '1px solid var(--hz-rule)',
        borderRadius: 'var(--hz-lg)',
        padding: '20px 24px',
        background: 'var(--hz-bg)',
      }}
    >
      <h2 className="hz-h2" style={{ fontSize: '15px', margin: '0 0 16px', color: 'var(--hz-ink)' }}>Repository context</h2>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3 text-sm" style={{ color: 'var(--hz-ink2)' }}>
        {repo.repo_type && (
          <>
            <dt className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Type</dt>
            <dd style={{ color: 'var(--hz-ink)' }} className="capitalize">
              {repo.repo_type}
              {repo.app_subtype ? ` · ${repo.app_subtype.replace(/_/g, ' ')}` : ''}
              {repo.iac_provider ? ` · ${repo.iac_provider}` : ''}
            </dd>
          </>
        )}
        {repo.language && repo.language.length > 0 && (
          <>
            <dt className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Languages</dt>
            <dd className="flex flex-wrap items-center gap-2" style={{ color: 'var(--hz-ink)' }}>
              {repo.language.map((lang) => (
                <span key={lang} className="inline-flex items-center gap-1">
                  <LanguageLogo language={lang} />
                  {lang}
                </span>
              ))}
            </dd>
          </>
        )}
        {repo.observability_backend && (
          <>
            <dt className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Observability</dt>
            <dd className="flex items-center gap-2 capitalize" style={{ color: 'var(--hz-ink)' }}>
              <ObsBackendLogo backend={repo.observability_backend} />
              {repo.observability_backend}
            </dd>
          </>
        )}
        {repo.instrumentation && (
          <>
            <dt className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Instrumentation</dt>
            <dd className="flex items-center gap-2" style={{ color: 'var(--hz-ink)' }}>
              <InstrumentationLogo value={repo.instrumentation} />
              <span>{instrumentationLabel(repo.instrumentation)}</span>
            </dd>
          </>
        )}
        {Object.keys(tags).length > 0 && (
          <>
            <dt className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Tags / labels</dt>
            <dd className="font-mono text-xs" style={{ color: 'var(--hz-ink)' }}>
              {Object.entries(tags).map(([k, v]) => (
                <span key={k} className="mr-3">
                  {k}={String(v)}
                </span>
              ))}
            </dd>
          </>
        )}
        {Boolean(meta.service_name || meta.environment) && (
          <>
            <dt className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Service</dt>
            <dd style={{ color: 'var(--hz-ink)' }}>
              {[meta.service_name, meta.environment].filter(Boolean).join(' · ')}
            </dd>
          </>
        )}
        {repo.context_summary && (
          <>
            <dt className="hz-sm sm:col-span-1" style={{ color: 'var(--hz-muted)' }}>Summary</dt>
            <dd className="sm:col-span-1 whitespace-pre-wrap" style={{ color: 'var(--hz-ink2)' }}>{repo.context_summary}</dd>
          </>
        )}
      </dl>
      {!repo.repo_type &&
        !repo.language?.length &&
        !repo.observability_backend &&
        !repo.instrumentation &&
        !repo.context_summary &&
        Object.keys(tags).length === 0 && (
          <p className="hz-body" style={{ color: 'var(--hz-muted)' }}>No context configured yet. Edit context from the repositories list.</p>
        )}

      {recommendation && (
        <div className="mt-5">
          <InstrumentationRecommendationCard recommendation={recommendation} />
        </div>
      )}
    </div>
  )
}

export default function RepositoryDetailPage() {
  const params = useParams()
  const repoId = params.repoId as string

  const { data: repo, isLoading: repoLoading, error: repoError } = useQuery({
    queryKey: ['repository', repoId],
    queryFn: () => reposApi.get(repoId),
    enabled: !!repoId,
  })

  const { data: latestRepositoryAnalysis } = useQuery({
    queryKey: ['analyses', 'repo', repoId, 'latest-repository'],
    queryFn: () =>
      analysesApi.list({
        repo_id: repoId,
        analysis_type: 'repository',
        status: 'completed',
        limit: 1,
        sort: 'created_at',
        order: 'desc',
      }),
    enabled: !!repoId && !!repo,
  })

  const { data: analysesList } = useQuery({
    queryKey: ['analyses', 'repo', repoId, 'all'],
    queryFn: () =>
      analysesApi.list({
        repo_id: repoId,
        limit: 100,
        sort: 'created_at',
        order: 'desc',
      }),
    enabled: !!repoId && !!repo,
  })

  const latestRepoJob: AnalysisJob | undefined = latestRepositoryAnalysis?.items[0]
  const items = analysesList?.items ?? []

  if (repoLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '200px', background: 'var(--hz-bg)' }}>
        <span className="hz-cursor" style={{ opacity: 0.35 }} aria-hidden />
      </div>
    )
  }

  if (repoError || !repo) {
    return (
      <div style={{ padding: '24px', background: 'var(--hz-bg)' }}>
        <Link href="/repositories" className="hz-sm inline-flex items-center gap-1 mb-4 hover:underline" style={{ color: 'var(--hz-muted)' }}>
          <ArrowLeft className="h-4 w-4" />
          Back to repositories
        </Link>
        <p style={{ color: 'var(--hz-crit)', fontSize: '13px' }}>Repository not found.</p>
      </div>
    )
  }

  const score = latestRepoJob?.score_global ?? null
  const grade = score != null ? getScoreGrade(score) : ''

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%', background: 'var(--hz-bg)' }}>
      <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--hz-rule)' }}>
        <Link
          href="/repositories"
          className="hz-sm inline-flex items-center gap-1.5 hover:underline"
          style={{ color: 'var(--hz-muted)' }}
        >
          <ArrowLeft className="h-4 w-4 shrink-0" />
          Repositories
        </Link>
      </div>

      <div style={{ padding: '20px 24px 0', display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'flex-start' }}>
        <ScmLogo scm={repo.scm_type} className="h-11 w-11 shrink-0" />
        <div className="min-w-0 flex-1">
          <h1 className="hz-h2" style={{ margin: 0, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px' }}>
            <span className="truncate" style={{ color: 'var(--hz-ink)' }}>{repo.full_name}</span>
            <a
              href={repo.web_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--hz-muted)' }}
              className="shrink-0 hover:opacity-80"
              title="Open on Git host"
            >
              <ExternalLink className="h-5 w-5" />
            </a>
          </h1>
          <p className="hz-body" style={{ marginTop: '6px', marginBottom: 0, fontSize: '12px', color: 'var(--hz-muted)' }}>
            Default branch <span style={{ fontWeight: 500, color: 'var(--hz-ink2)' }}>{repo.default_branch}</span>
            {repo.last_analysis_at && (
              <> · Last analysis {formatDate(repo.last_analysis_at)}</>
            )}
          </p>
        </div>
      </div>

      <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '1200px', width: '100%' }}>
        {/* Latest repository-type analysis score */}
        <div
          style={{
            border: '1px solid var(--hz-rule)',
            borderRadius: 'var(--hz-lg)',
            padding: '20px 24px',
            position: 'relative',
            overflow: 'hidden',
            background: 'var(--hz-bg)',
          }}
        >
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: 'var(--hz-info)' }} />
          <div className="hz-grid-bg" style={{ position: 'absolute', inset: 0, opacity: 0.4, pointerEvents: 'none' }} />
          <h2 className="hz-h2" style={{ fontSize: '14px', margin: '0 0 4px', position: 'relative', color: 'var(--hz-ink)' }}>
            Latest repository analysis
          </h2>
          <p className="hz-sm" style={{ margin: '0 0 16px', position: 'relative', color: 'var(--hz-muted)' }}>
            Score from the most recent completed analysis with type &quot;repository&quot; (full codebase scan).
          </p>
          {!latestRepoJob ? (
            <p className="hz-body" style={{ color: 'var(--hz-muted)', position: 'relative' }}>No completed repository analysis yet.</p>
          ) : (
            <div className="flex flex-col sm:flex-row sm:items-center gap-4" style={{ position: 'relative' }}>
              <div className="flex items-baseline gap-3">
                <span
                  className="tabular-nums"
                  style={{ fontSize: '40px', fontWeight: 700, letterSpacing: '-0.04em', color: score != null ? hzGradeColorVar(grade) : 'var(--hz-muted)' }}
                >
                  {score ?? '—'}
                </span>
                {score !== null && (
                  <span className="tabular-nums hz-h2" style={{ fontSize: '18px', color: hzGradeColorVar(grade) }}>{grade}</span>
                )}
              </div>
              <div className="flex-1 hz-body" style={{ fontSize: '13px', color: 'var(--hz-muted)' }}>
                <p style={{ margin: 0 }}>
                  {latestRepoJob.completed_at && <>Finished {formatDate(latestRepoJob.completed_at)}</>}
                  {latestRepoJob.branch_ref && <> · Ref {latestRepoJob.branch_ref}</>}
                </p>
                <Link
                  href={`/analyses/${latestRepoJob.id}`}
                  className="inline-block mt-2 font-medium hover:underline"
                  style={{ color: 'var(--hz-ink)' }}
                >
                  View analysis details →
                </Link>
              </div>
            </div>
          )}
        </div>

        <ContextSection repo={repo} latestAnalysis={latestRepoJob} />

        <div style={{ border: '1px solid var(--hz-rule)', borderRadius: 'var(--hz-lg)', overflow: 'hidden', background: 'var(--hz-bg)' }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)' }}>
            <h2 className="hz-h2" style={{ fontSize: '14px', margin: 0, color: 'var(--hz-ink)' }}>All analyses</h2>
            <p className="hz-sm" style={{ margin: '4px 0 0', color: 'var(--hz-muted)' }}>
              {analysesList?.total ?? items.length} job{analysesList?.total === 1 ? '' : 's'} for this repository
            </p>
          </div>
          {items.length === 0 ? (
            <div className="hz-body" style={{ padding: '32px', textAlign: 'center', color: 'var(--hz-muted)' }}>No analyses yet.</div>
          ) : (
            <div className="overflow-x-auto">
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)' }}>
                    {['Started', 'Type', 'Status', 'Score', ''].map((h) => (
                      <th
                        key={h || 'act'}
                        className="hz-label"
                        style={{
                          textAlign: h ? 'left' : 'right',
                          padding: '10px 16px',
                          fontWeight: 400,
                          color: 'var(--hz-muted)',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((job) => (
                    <tr
                      key={job.id}
                      style={{ borderBottom: '1px solid var(--hz-rule)' }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = 'var(--hz-bg2)' }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = 'transparent' }}
                    >
                      <td style={{ padding: '10px 16px', whiteSpace: 'nowrap', color: 'var(--hz-ink)' }}>{formatDate(job.created_at)}</td>
                      <td style={{ padding: '10px 16px', textTransform: 'capitalize', color: 'var(--hz-ink2)' }}>{job.analysis_type.replace(/_/g, ' ')}</td>
                      <td style={{ padding: '10px 16px' }}><HzStatusBadge status={job.status} /></td>
                      <td className="tabular-nums" style={{ padding: '10px 16px', color: 'var(--hz-ink)' }}>
                        {job.status === 'completed' && job.score_global != null ? job.score_global : '—'}
                      </td>
                      <td style={{ padding: '10px 16px', textAlign: 'right' }}>
                        <Link href={`/analyses/${job.id}`} className="font-medium hover:underline" style={{ color: 'var(--hz-info)' }}>
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
