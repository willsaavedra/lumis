'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Folder, FileCode, Loader2 } from 'lucide-react'
import { reposApi } from '@/lib/api'

export type ScopeItem = { path: string; kind: 'file' | 'dir' }

type Props = {
  repoId: string
  refName: string
  selection: ScopeItem[]
  onSelectionChange: (items: ScopeItem[]) => void
  /** Override scroll area max-height (e.g. taller panel inside wide modals) */
  listMaxHeightClassName?: string
}

function parentPath(p: string): string {
  if (!p) return ''
  const i = p.lastIndexOf('/')
  return i <= 0 ? '' : p.slice(0, i)
}

export function RepoContentsPicker({
  repoId,
  refName,
  selection,
  onSelectionChange,
  listMaxHeightClassName = 'max-h-[min(42vh,16rem)] sm:max-h-72 lg:max-h-[22rem]',
}: Props) {
  const [browsePath, setBrowsePath] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['repo-contents', repoId, refName, browsePath],
    queryFn: () => reposApi.listContents(repoId, { ref: refName, path: browsePath }),
    enabled: !!repoId && !!refName,
    staleTime: 30_000,
  })

  const selectedSet = new Map(selection.map((s) => [s.path, s.kind]))

  function toggle(path: string, kind: 'file' | 'dir', checked: boolean) {
    const next = selection.filter((s) => s.path !== path)
    if (checked) next.push({ path, kind })
    onSelectionChange(next)
  }

  const crumbs = browsePath ? browsePath.split('/') : []

  const crumbBtn = {
    base: {
      color: 'var(--hz-ink2)',
      background: 'transparent',
      border: 'none',
      cursor: 'pointer' as const,
      padding: 0,
    },
  }

  return (
    <div
      className="rounded-md overflow-hidden"
      style={{
        border: '1px solid var(--hz-rule)',
        background: 'var(--hz-bg2)',
        borderRadius: 'var(--hz-md)',
      }}
    >
      <div
        className="px-3 py-2 flex items-center gap-1 text-xs flex-wrap hz-sm"
        style={{ borderBottom: '1px solid var(--hz-rule)' }}
      >
        <button
          type="button"
          onClick={() => setBrowsePath('')}
          className="font-medium"
          style={crumbBtn.base}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = 'var(--hz-ink)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = 'var(--hz-ink2)'
          }}
        >
          root
        </button>
        {crumbs.map((part, i) => {
          const prefix = crumbs.slice(0, i + 1).join('/')
          return (
            <span key={prefix} className="inline-flex items-center gap-1">
              <ChevronRight className="h-3 w-3 shrink-0 opacity-50" style={{ color: 'var(--hz-muted)' }} />
              <button
                type="button"
                onClick={() => setBrowsePath(prefix)}
                className="truncate max-w-[120px]"
                style={crumbBtn.base}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = 'var(--hz-ink)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = 'var(--hz-ink2)'
                }}
              >
                {part}
              </button>
            </span>
          )
        })}
      </div>

      <div className={`overflow-y-auto p-2 space-y-0.5 ${listMaxHeightClassName}`}>
        {browsePath ? (
          <button
            type="button"
            onClick={() => setBrowsePath(parentPath(browsePath))}
            className="w-full text-left px-2 py-1.5 rounded text-xs flex items-center gap-2"
            style={{
              color: 'var(--hz-ink2)',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              borderRadius: 'var(--hz-sm)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'var(--hz-bg3)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'transparent'
            }}
          >
            <span style={{ color: 'var(--hz-muted)' }}>..</span>
            <span>Parent folder</span>
          </button>
        ) : null}

        {isLoading && (
          <div className="flex items-center justify-center gap-2 py-6 text-xs hz-sm">
            <Loader2 className="h-4 w-4 animate-spin shrink-0" style={{ color: 'var(--hz-muted)' }} />
            Loading tree…
          </div>
        )}

        {error && (
          <p className="text-xs px-2 py-3" style={{ color: 'var(--hz-crit)' }}>
            Could not load files. Check branch and GitHub connection.
          </p>
        )}

        {!isLoading && data?.map((item) => {
          const isDir = item.type === 'dir'
          const checked = selectedSet.has(item.path)
          return (
            <div
              key={item.path}
              className="flex items-center gap-2 px-2 py-1 rounded"
              style={{ borderRadius: 'var(--hz-sm)' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'var(--hz-bg3)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent'
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => toggle(item.path, isDir ? 'dir' : 'file', e.target.checked)}
                className="rounded shrink-0"
                style={{
                  accentColor: 'var(--hz-ink)',
                  border: '1px solid var(--hz-rule2)',
                }}
                aria-label={isDir ? `Folder ${item.name}` : `File ${item.name}`}
              />
              {isDir ? (
                <button
                  type="button"
                  onClick={() => setBrowsePath(item.path)}
                  className="flex-1 min-w-0 flex items-center gap-2 text-left text-xs"
                  style={{
                    color: 'var(--hz-ink)',
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    padding: 0,
                  }}
                >
                  <Folder className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--hz-info)' }} />
                  <span className="truncate font-medium">{item.name}/</span>
                </button>
              ) : (
                <span className="flex-1 min-w-0 flex items-center gap-2 text-xs" style={{ color: 'var(--hz-ink2)' }}>
                  <FileCode className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--hz-muted)' }} />
                  <span className="truncate">{item.name}</span>
                </span>
              )}
            </div>
          )
        })}
      </div>

      {selection.length > 0 && (
        <div
          className="px-3 py-2 hz-micro"
          style={{
            borderTop: '1px solid var(--hz-rule)',
            color: 'var(--hz-muted)',
          }}
        >
          {selection.length} path{selection.length === 1 ? '' : 's'} selected
        </div>
      )}
    </div>
  )
}

/**
 * Maps UI scope to API payload. Quick always stays `quick` — dirs are expanded on the worker.
 * Full / repository: optional scope limits the walk; empty scope means whole repo (full) or deep prioritized scan (repository).
 */
export function resolveScopeAnalysisType(
  analyzeType: 'quick' | 'full' | 'repository',
  scope: ScopeItem[],
): { analysisType: 'quick' | 'full' | 'repository'; changedFiles: string[] | null } {
  const paths = scope.length > 0 ? scope.map((s) => s.path) : null
  return { analysisType: analyzeType, changedFiles: paths }
}
