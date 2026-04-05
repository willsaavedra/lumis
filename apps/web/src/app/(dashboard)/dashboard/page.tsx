'use client'

import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { analysesApi, billingApi, reposApi } from '@/lib/api'
import { RepoWebLink } from '@/components/RepoWebLink'
import { getScoreGrade, getScoreColor, formatRelativeTime } from '@/lib/utils'
import Link from 'next/link'

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

  const creditPct = usage ? Math.round((usage.credits_used / usage.credits_included) * 100) : 0

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Dashboard</h1>
        <p className="text-gray-500 dark:text-gray-400">Overview of your observability health</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <div className="bg-white dark:bg-gray-900 p-5 rounded-xl border border-gray-200 dark:border-gray-700">
          <div className="text-sm text-gray-500 dark:text-gray-400 mb-1">Global Score</div>
          <div className={`text-3xl font-bold ${avgScore ? getScoreColor(avgScore) : 'text-gray-400'}`}>
            {avgScore ?? '—'}
            {avgScore && <span className="text-base ml-1">({getScoreGrade(avgScore)})</span>}
          </div>
        </div>

        <div className="bg-white dark:bg-gray-900 p-5 rounded-xl border border-gray-200 dark:border-gray-700">
          <div className="text-sm text-gray-500 dark:text-gray-400 mb-1">Analyses this month</div>
          <div className="text-3xl font-bold text-gray-900 dark:text-gray-100">{completedAnalyses.length}</div>
        </div>

        <div className="bg-white dark:bg-gray-900 p-5 rounded-xl border border-gray-200 dark:border-gray-700">
          <div className="text-sm text-gray-500 dark:text-gray-400 mb-1">Active Repositories</div>
          <div className="text-3xl font-bold text-gray-900 dark:text-gray-100">{repos?.length ?? 0}</div>
        </div>

        <div className="bg-white dark:bg-gray-900 p-5 rounded-xl border border-gray-200 dark:border-gray-700">
          <div className="text-sm text-gray-500 dark:text-gray-400 mb-1">Credits Used</div>
          <div className="text-3xl font-bold text-gray-900 dark:text-gray-100">{usage?.credits_used ?? 0}</div>
          <div className="text-xs text-gray-400 dark:text-gray-500">of {usage?.credits_included ?? 0} included</div>
          <div className="mt-2 h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full">
            <div
              className={`h-1.5 rounded-full ${creditPct > 80 ? 'bg-orange-500' : 'bg-brand-500'}`}
              style={{ width: `${Math.min(100, creditPct)}%` }}
            />
          </div>
        </div>
      </div>

      {/* Recent Analyses */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between p-5 border-b border-gray-200 dark:border-gray-700">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100">Recent Analyses</h2>
          <Link href="/analyses" className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">
            View all
          </Link>
        </div>
        <div className="divide-y divide-gray-100 dark:divide-gray-800">
          {analyses?.length === 0 && (
            <div className="p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
              No analyses yet. Connect a repository to get started.
            </div>
          )}
          {analyses?.map((job) => (
            <div
              key={job.id}
              role="button"
              tabIndex={0}
              onClick={() => router.push(`/analyses/${job.id}`)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  router.push(`/analyses/${job.id}`)
                }
              }}
              className="flex items-center justify-between p-4 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors cursor-pointer"
            >
              <div>
                <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {job.repo_web_url && job.repo_full_name ? (
                    <RepoWebLink name={job.repo_full_name} href={job.repo_web_url} />
                  ) : (
                    job.repo_full_name ?? 'unknown repo'
                  )}
                </div>
                <div className="text-xs text-gray-400 dark:text-gray-500">
                  {job.commit_sha ? job.commit_sha.slice(0, 7) : job.trigger} · {formatRelativeTime(job.created_at)}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <StatusBadge status={job.status} />
                {job.score_global !== null && (
                  <span className={`text-sm font-bold ${getScoreColor(job.score_global)}`}>
                    {job.score_global}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
    running: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 animate-pulse',
    pending: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400',
    failed: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'}`}>
      {status}
    </span>
  )
}
