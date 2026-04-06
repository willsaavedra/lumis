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
import { formatDate, formatLlmProvider, getScoreColor, getScoreGrade, cn } from '@/lib/utils'

function statusBadge(status: string) {
  const map: Record<string, string> = {
    completed: 'bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-300 border-green-200 dark:border-green-800',
    running: 'bg-blue-50 dark:bg-blue-900/20 text-blue-800 dark:text-blue-300 border-blue-200 dark:border-blue-800',
    pending: 'bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800',
    failed: 'bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-300 border-red-200 dark:border-red-800',
  }
  return (
    <span
      className={cn(
        'inline-flex px-2 py-0.5 rounded text-xs font-medium border capitalize',
        map[status] ?? 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300',
      )}
    >
      {status}
    </span>
  )
}

function ContextSection({ repo, latestAnalysis }: { repo: Repository; latestAnalysis?: import('@/lib/api').AnalysisJob | null }) {
  const meta = (repo.obs_metadata ?? {}) as Record<string, unknown>
  const tags = (meta.tags ?? meta.labels ?? {}) as Record<string, string>
  const recommendation = getInstrumentationRecommendation(repo, latestAnalysis)

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Repository context</h2>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3 text-sm">
        {repo.repo_type && (
          <>
            <dt className="text-gray-500 dark:text-gray-400">Type</dt>
            <dd className="text-gray-900 dark:text-gray-100 capitalize">
              {repo.repo_type}
              {repo.app_subtype ? ` · ${repo.app_subtype.replace(/_/g, ' ')}` : ''}
              {repo.iac_provider ? ` · ${repo.iac_provider}` : ''}
            </dd>
          </>
        )}
        {repo.language && repo.language.length > 0 && (
          <>
            <dt className="text-gray-500 dark:text-gray-400">Languages</dt>
            <dd className="flex flex-wrap items-center gap-2 text-gray-900 dark:text-gray-100">
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
            <dt className="text-gray-500 dark:text-gray-400">Observability</dt>
            <dd className="flex items-center gap-2 text-gray-900 dark:text-gray-100 capitalize">
              <ObsBackendLogo backend={repo.observability_backend} />
              {repo.observability_backend}
            </dd>
          </>
        )}
        {repo.instrumentation && (
          <>
            <dt className="text-gray-500 dark:text-gray-400">Instrumentation</dt>
            <dd className="flex items-center gap-2 text-gray-900 dark:text-gray-100">
              <InstrumentationLogo value={repo.instrumentation} />
              <span>{instrumentationLabel(repo.instrumentation)}</span>
            </dd>
          </>
        )}
        {Object.keys(tags).length > 0 && (
          <>
            <dt className="text-gray-500 dark:text-gray-400">Tags / labels</dt>
            <dd className="text-gray-900 dark:text-gray-100 font-mono text-xs">
              {Object.entries(tags).map(([k, v]) => (
                <span key={k} className="mr-3">
                  {k}={String(v)}
                </span>
              ))}
            </dd>
          </>
        )}
        {(meta.service_name || meta.environment) && (
          <>
            <dt className="text-gray-500 dark:text-gray-400">Service</dt>
            <dd className="text-gray-900 dark:text-gray-100">
              {[meta.service_name, meta.environment].filter(Boolean).join(' · ')}
            </dd>
          </>
        )}
        {repo.context_summary && (
          <>
            <dt className="text-gray-500 dark:text-gray-400 sm:col-span-1">Summary</dt>
            <dd className="text-gray-900 dark:text-gray-100 sm:col-span-1 whitespace-pre-wrap">{repo.context_summary}</dd>
          </>
        )}
      </dl>
      {!repo.repo_type &&
        !repo.language?.length &&
        !repo.observability_backend &&
        !repo.instrumentation &&
        !repo.context_summary &&
        Object.keys(tags).length === 0 && (
          <p className="text-sm text-gray-500 dark:text-gray-400">No context configured yet. Edit context from the repositories list.</p>
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
      <div className="p-8 flex justify-center">
        <div className="w-8 h-8 border-2 border-gray-300 border-t-gray-900 rounded-full animate-spin dark:border-gray-600 dark:border-t-gray-100" />
      </div>
    )
  }

  if (repoError || !repo) {
    return (
      <div className="p-8">
        <Link href="/repositories" className="text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 inline-flex items-center gap-1 mb-4">
          <ArrowLeft className="h-4 w-4" />
          Back to repositories
        </Link>
        <p className="text-red-600 dark:text-red-400">Repository not found.</p>
      </div>
    )
  }

  const score = latestRepoJob?.score_global ?? null
  const grade = score != null ? getScoreGrade(score) : ''
  const scoreColorClass = score != null ? getScoreColor(score) : ''

  return (
    <div className="p-8 w-full min-w-0 max-w-none">
      <Link
        href="/repositories"
        className="text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 inline-flex items-center gap-1 mb-6"
      >
        <ArrowLeft className="h-4 w-4" />
        Repositories
      </Link>

      <div className="flex items-start gap-3 min-w-0 mb-8">
        <ScmLogo scm={repo.scm_type} className="h-10 w-10 shrink-0 mt-0.5" />
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 truncate flex items-center gap-2">
            {repo.full_name}
            <a
              href={repo.web_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 shrink-0"
              title="Open on Git host"
            >
              <ExternalLink className="h-5 w-5" />
            </a>
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Default branch <span className="font-medium">{repo.default_branch}</span>
            {repo.last_analysis_at && (
              <>
                {' '}
                · Last analysis {formatDate(repo.last_analysis_at)}
              </>
            )}
          </p>
        </div>
      </div>

      {/* Latest repository-type analysis score */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1">Latest repository analysis</h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
          Score from the most recent completed analysis with type &quot;repository&quot; (full codebase scan).
        </p>
        {!latestRepoJob ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">No completed repository analysis yet.</p>
        ) : (
          <div className="flex flex-col sm:flex-row sm:items-center gap-4">
            <div className={cn('flex items-baseline gap-3', scoreColorClass)}>
              <span className="text-5xl font-bold tabular-nums">{score ?? '—'}</span>
              {score !== null && <span className="text-xl font-medium tabular-nums">{grade}</span>}
            </div>
            <div className="flex-1 text-sm text-gray-600 dark:text-gray-400">
              <p>
                {latestRepoJob.completed_at && <>Finished {formatDate(latestRepoJob.completed_at)}</>}
                {latestRepoJob.branch_ref && (
                  <>
                    {' '}
                    · Ref {latestRepoJob.branch_ref}
                  </>
                )}
                {' '}
                · LLM {formatLlmProvider(latestRepoJob.llm_provider)}
              </p>
              <Link
                href={`/analyses/${latestRepoJob.id}`}
                className="inline-block mt-2 text-gray-900 dark:text-gray-100 font-medium hover:underline"
              >
                View analysis details
              </Link>
            </div>
          </div>
        )}
      </div>

      <div className="mb-6">
        <ContextSection repo={repo} latestAnalysis={latestRepoJob} />
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-800">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">All analyses</h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            {analysesList?.total ?? items.length} job{analysesList?.total === 1 ? '' : 's'} for this repository
          </p>
        </div>
        {items.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-500 dark:text-gray-400">No analyses yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800 text-left text-gray-500 dark:text-gray-400">
                  <th className="px-6 py-3 font-medium">Started</th>
                  <th className="px-6 py-3 font-medium">Type</th>
                  <th className="px-6 py-3 font-medium">LLM</th>
                  <th className="px-6 py-3 font-medium">Status</th>
                  <th className="px-6 py-3 font-medium">Score</th>
                  <th className="px-6 py-3 font-medium w-24" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {items.map((job) => (
                  <tr key={job.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                    <td className="px-6 py-3 text-gray-900 dark:text-gray-100 whitespace-nowrap">{formatDate(job.created_at)}</td>
                    <td className="px-6 py-3 capitalize text-gray-700 dark:text-gray-300">{job.analysis_type.replace(/_/g, ' ')}</td>
                    <td className="px-6 py-3 text-gray-700 dark:text-gray-300 whitespace-nowrap">{formatLlmProvider(job.llm_provider)}</td>
                    <td className="px-6 py-3">{statusBadge(job.status)}</td>
                    <td className="px-6 py-3 tabular-nums text-gray-900 dark:text-gray-100">
                      {job.status === 'completed' && job.score_global != null ? job.score_global : '—'}
                    </td>
                    <td className="px-6 py-3">
                      <Link href={`/analyses/${job.id}`} className="text-gray-900 dark:text-gray-100 font-medium hover:underline">
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
  )
}
