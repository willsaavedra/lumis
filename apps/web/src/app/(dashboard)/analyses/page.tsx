'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { analysesApi, reposApi, type AnalysisJob, type AnalysisListParams } from '@/lib/api'
import { ScmLogo } from '@/components/ScmLogo'
import { getScoreColor, formatRelativeTime, getScoreGrade } from '@/lib/utils'

const PAGE_SIZES = [10, 20, 50] as const
const SORT_COLUMNS: { key: AnalysisListParams['sort']; label: string }[] = [
  { key: 'repo', label: 'Repo' },
  { key: 'trigger', label: 'Trigger' },
  { key: 'analysis_type', label: 'Type' },
  { key: 'status', label: 'Status' },
  { key: 'score_global', label: 'Score' },
  { key: 'credits_consumed', label: 'Credits' },
  { key: 'created_at', label: 'Date' },
]

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

  useEffect(() => {
    setPage(0)
  }, [debouncedQ, status, trigger, analysisType, repoId, fixPr, pageSize])

  const listParams: AnalysisListParams = useMemo(
    () => ({
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
    }),
    [page, pageSize, sort, order, debouncedQ, status, trigger, analysisType, repoId, fixPr],
  )

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

  const toggleSort = useCallback((column: string) => {
    if (sort === column) {
      setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(column)
      setOrder(column === 'repo' || column === 'status' ? 'asc' : 'desc')
    }
  }, [sort])

  if (isLoading && !data) {
    return <div className="p-8 text-gray-400 dark:text-gray-500">Loading...</div>
  }

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Analyses</h1>
        <p className="text-gray-500 dark:text-gray-400">History of all observability analyses</p>
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-col gap-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-gray-500 dark:text-gray-400">Search repo</span>
            <input
              type="search"
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              placeholder="owner/name…"
              className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-gray-500 dark:text-gray-400">Repository</span>
            <select
              value={repoId}
              onChange={(e) => setRepoId(e.target.value)}
              className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100"
            >
              <option value="">All</option>
              {repos?.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.full_name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-gray-500 dark:text-gray-400">Status</span>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100"
            >
              <option value="">All</option>
              <option value="pending">pending</option>
              <option value="running">running</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-gray-500 dark:text-gray-400">Trigger</span>
            <select
              value={trigger}
              onChange={(e) => setTrigger(e.target.value)}
              className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100"
            >
              <option value="">All</option>
              <option value="pr">pr</option>
              <option value="push">push</option>
              <option value="manual">manual</option>
              <option value="scheduled">scheduled</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-gray-500 dark:text-gray-400">Type</span>
            <select
              value={analysisType}
              onChange={(e) => setAnalysisType(e.target.value)}
              className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100"
            >
              <option value="">All</option>
              <option value="quick">quick</option>
              <option value="full">full</option>
              <option value="repository">repository</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-gray-500 dark:text-gray-400">Fix PR</span>
            <select
              value={fixPr}
              onChange={(e) => setFixPr(e.target.value as typeof fixPr)}
              className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1.5 text-sm text-gray-900 dark:text-gray-100"
            >
              <option value="">All</option>
              <option value="has_pr">PR suggested (open)</option>
              <option value="generating">Generating PR…</option>
              <option value="can_suggest">Can suggest PR</option>
            </select>
          </label>
        </div>
        <div className="flex items-center justify-between gap-2 flex-wrap text-xs text-gray-500 dark:text-gray-400">
          <span>
            {total} result{total !== 1 ? 's' : ''}
            {isPlaceholderData && ' (updating…)'}
          </span>
          <button
            type="button"
            onClick={() => {
              setQInput('')
              setDebouncedQ('')
              setStatus('')
              setTrigger('')
              setAnalysisType('')
              setRepoId('')
              setFixPr('')
              setSort('created_at')
              setOrder('desc')
            }}
            className="text-gray-600 dark:text-gray-300 hover:underline"
          >
            Clear filters
          </button>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 overflow-x-auto">
        <table className="w-full min-w-[900px]">
          <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
            <tr>
              <SortableTh label="Repo" column="repo" sort={sort} order={order} onSort={toggleSort} />
              <SortableTh label="Trigger" column="trigger" sort={sort} order={order} onSort={toggleSort} />
              <SortableTh label="Type" column="analysis_type" sort={sort} order={order} onSort={toggleSort} />
              <SortableTh label="Status" column="status" sort={sort} order={order} onSort={toggleSort} />
              <SortableTh label="Score" column="score_global" sort={sort} order={order} onSort={toggleSort} />
              <SortableTh label="Credits" column="credits_consumed" sort={sort} order={order} onSort={toggleSort} />
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                Fix PR
              </th>
              <SortableTh label="Date" column="created_at" sort={sort} order={order} onSort={toggleSort} />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {items.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center text-sm text-gray-400 dark:text-gray-500">
                  No analyses match your filters.
                </td>
              </tr>
            )}
            {items.map((job) => (
              <tr
                key={job.id}
                className="hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer"
                onClick={() => router.push(`/analyses/${job.id}`)}
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <ScmLogo scm={job.scm_type} className="h-5 w-5 shrink-0" />
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                      {job.repo_full_name ?? job.repo_id.slice(0, 8)}
                    </span>
                  </div>
                  <div className="text-xs text-gray-400 dark:text-gray-500 flex items-center gap-1.5 mt-0.5">
                    {job.branch_ref && <span className="font-mono">{job.branch_ref}</span>}
                    {job.branch_ref && job.commit_sha && <span>·</span>}
                    {job.commit_sha && <span className="font-mono">{job.commit_sha.slice(0, 7)}</span>}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="text-xs bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded text-gray-700 dark:text-gray-300">
                    {job.trigger}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">{job.analysis_type}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={job.status} />
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-col gap-0.5 items-start">
                    {job.score_global !== null && job.score_global !== undefined ? (
                      <span className={`font-bold text-sm ${getScoreColor(job.score_global)}`}>
                        {job.score_global} ({getScoreGrade(job.score_global)})
                      </span>
                    ) : (
                      <span className="text-gray-400 dark:text-gray-500 text-sm">—</span>
                    )}
                    {(() => {
                      const d = job.result?.crossrun_summary?.score_delta
                      if (d == null || Number.isNaN(d)) return null
                      return (
                        <span
                          className={`text-[11px] font-medium tabular-nums ${
                            d > 0
                              ? 'text-green-600 dark:text-green-400'
                              : d < 0
                                ? 'text-red-500 dark:text-red-400'
                                : 'text-gray-500 dark:text-gray-400'
                          }`}
                        >
                          {d > 0 ? `↑${d}` : d < 0 ? `↓${Math.abs(d)}` : '0'} vs prev
                        </span>
                      )
                    })()}
                  </div>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">{job.credits_consumed ?? '—'}</td>
                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  <FixPrCell job={job} />
                </td>
                <td className="px-4 py-3 text-sm text-gray-400 dark:text-gray-500 whitespace-nowrap">
                  {formatRelativeTime(job.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="mt-4 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-gray-600 dark:text-gray-400">
        <div className="flex items-center gap-2">
          <span>Rows per page</span>
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value))
              setPage(0)
            }}
            className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm"
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={page <= 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-600 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            Previous
          </button>
          <span className="tabular-nums px-2">
            {pageStart}–{pageEnd} of {total}
          </span>
          <button
            type="button"
            disabled={page >= totalPages - 1 || total === 0}
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-600 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}

function SortableTh({
  label,
  column,
  sort,
  order,
  onSort,
}: {
  label: string
  column: string
  sort: string
  order: 'asc' | 'desc'
  onSort: (c: string) => void
}) {
  const active = sort === column
  return (
    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
      <button
        type="button"
        onClick={() => onSort(column)}
        className={`inline-flex items-center gap-1 hover:text-gray-900 dark:hover:text-gray-200 ${active ? 'text-gray-900 dark:text-gray-100' : ''}`}
      >
        {label}
        {active && <span aria-hidden className="text-[10px]">{order === 'asc' ? '↑' : '↓'}</span>}
      </button>
    </th>
  )
}

function FixPrCell({ job }: { job: AnalysisJob }) {
  if (job.fix_pr_url) {
    return (
      <a
        href={job.fix_pr_url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 rounded-md bg-green-100 dark:bg-green-900/30 px-2 py-1 text-xs font-medium text-green-800 dark:text-green-300 hover:underline"
        title="Open suggested PR"
      >
        PR suggested
      </a>
    )
  }
  if (job.fix_pr_pending) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-md bg-blue-100 dark:bg-blue-900/30 px-2 py-1 text-xs font-medium text-blue-800 dark:text-blue-300"
        title="Fix PR is being generated"
      >
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
        Generating…
      </span>
    )
  }
  if (job.status === 'completed' && job.fix_pr_eligible) {
    return (
      <span
        className="inline-flex rounded-md bg-amber-100 dark:bg-amber-900/25 px-2 py-1 text-xs font-medium text-amber-900 dark:text-amber-200"
        title="Actionable recommendations — open detail to create a fix PR"
      >
        Can suggest PR
      </span>
    )
  }
  if (job.status === 'completed' && !job.fix_pr_eligible) {
    return (
      <span
        className="text-xs text-gray-500 dark:text-gray-500"
        title="No critical/warning findings with file paths on metrics, logs, or traces"
      >
        No PR recommendations
      </span>
    )
  }
  return <span className="text-xs text-gray-400 dark:text-gray-600">—</span>
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
    running: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
    pending: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400',
    failed: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'}`}>
      {status}
    </span>
  )
}
