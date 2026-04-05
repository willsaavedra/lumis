'use client'

import { useMemo } from 'react'

export interface SuggestedFixFinding {
  file_path?: string
  line_start?: number
  suggestion?: string
  code_before?: string
  code_after?: string
}

function splitLines(s: string | undefined): string[] {
  if (!s) return []
  return s.replace(/\r\n/g, '\n').split('\n')
}

function linesEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  return a.every((line, i) => line === b[i])
}

/** Parse a unified-diff-style suggestion into left/right columns (GitHub-style). */
function parseUnifiedDiff(text: string): { left: string[]; right: string[]; stats: { add: number; del: number } } | null {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const left: string[] = []
  const right: string[] = []
  let add = 0
  let del = 0
  let sawMarker = false

  for (const raw of lines) {
    const line = raw
    if (line.startsWith('---') || line.startsWith('+++')) continue
    if (line.startsWith('@@')) {
      sawMarker = true
      continue
    }
    if (line.startsWith('-') && !line.startsWith('---')) {
      del += 1
      left.push(line.slice(1))
      sawMarker = true
      continue
    }
    if (line.startsWith('+') && !line.startsWith('+++')) {
      add += 1
      right.push(line.slice(1))
      sawMarker = true
      continue
    }
    if (line.startsWith(' ')) {
      const content = line.slice(1)
      left.push(content)
      right.push(content)
      sawMarker = true
      continue
    }
    if (sawMarker || left.length || right.length) {
      left.push(line)
      right.push(line)
    }
  }

  if (left.length === 0 && right.length === 0) return null
  return { left, right, stats: { add, del } }
}

function LineColumn({
  label,
  lines,
  startLine,
  variant,
}: {
  label: string
  lines: string[]
  startLine: number
  variant: 'current' | 'suggested' | 'neutral'
}) {
  const isCurrent = variant === 'current'
  const isNeutral = variant === 'neutral'
  return (
    <div
      className={`flex min-h-0 min-w-0 flex-1 flex-col border-gray-800 ${
        isNeutral
          ? 'bg-gray-900/40 md:border-r md:border-gray-800'
          : isCurrent
            ? 'border-b bg-red-950/35 dark:bg-red-950/25 md:border-b-0 md:border-r'
            : 'bg-green-950/35 dark:bg-green-950/25'
      }`}
    >
      <div
        className={`sticky top-0 z-10 flex items-center gap-2 border-b px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide ${
          isNeutral
            ? 'border-gray-800/80 bg-gray-900/90 text-gray-300'
            : isCurrent
              ? 'border-red-900/50 bg-red-950/80 text-red-300'
              : 'border-green-900/50 bg-green-950/80 text-green-300'
        }`}
      >
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            isNeutral ? 'bg-gray-500' : isCurrent ? 'bg-red-500' : 'bg-green-500'
          }`}
        />
        {label}
      </div>
      <div className="overflow-x-auto font-mono text-[11px] leading-relaxed">
        {lines.length === 0 ? (
          <div className="px-3 py-4 text-gray-500 italic">—</div>
        ) : (
          lines.map((line, i) => (
            <div
              key={`${variant}-${i}`}
              className={`flex border-b border-gray-900/40 last:border-b-0 ${
                isNeutral ? 'bg-gray-950/30' : isCurrent ? 'bg-red-950/20' : 'bg-green-950/20'
              }`}
            >
              <span
                className={`w-9 shrink-0 select-none border-r border-gray-800/80 py-0.5 pr-2 text-right tabular-nums text-gray-500 ${
                  isNeutral ? 'text-gray-400' : isCurrent ? 'text-red-200/50' : 'text-green-200/50'
                }`}
              >
                {startLine + i}
              </span>
              <span
                className={`min-w-0 flex-1 whitespace-pre py-0.5 pl-2 pr-3 ${
                  isNeutral ? 'text-gray-100/95' : isCurrent ? 'text-red-100/95' : 'text-green-100/95'
                }`}
              >
                {line || ' '}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export function SuggestedFixDiff({ finding }: { finding: SuggestedFixFinding }) {
  const before = finding.code_before
  const after = finding.code_after
  const suggestion = finding.suggestion ?? ''

  const mode = useMemo(() => {
    if (before || after) {
      const left = splitLines(before)
      let right = splitLines(after)
      /** LLM often omits code_after but puts the fix in suggestion — avoid an empty "Suggested" column. */
      const rightFromSuggestion =
        left.length > 0 && right.length === 0 && Boolean(suggestion?.trim())
      if (rightFromSuggestion) {
        right = splitLines(suggestion)
      }
      const statsSourceAfter = rightFromSuggestion ? suggestion : after
      return {
        kind: 'before_after' as const,
        left,
        right,
        stats: countChangeStats(before, statsSourceAfter),
        rightFromSuggestion,
      }
    }
    const parsed = parseUnifiedDiff(suggestion)
    if (parsed) {
      return {
        kind: 'unified' as const,
        left: parsed.left,
        right: parsed.right,
        stats: parsed.stats,
        rightFromSuggestion: false as const,
      }
    }
    return { kind: 'plain' as const, text: suggestion }
  }, [before, after, suggestion])

  const startLeft = finding.line_start ?? 1
  const startRight = finding.line_start ?? 1

  const identicalSides =
    (mode.kind === 'before_after' || mode.kind === 'unified') &&
    mode.left.length > 0 &&
    linesEqual(mode.left, mode.right)

  if (mode.kind === 'plain') {
    return (
      <div className="rounded-md border border-gray-800 bg-[#0d1117]">
        <div className="border-b border-gray-800 px-3 py-2 text-[11px] text-gray-400">
          {finding.file_path ? (
            <span className="font-mono text-gray-300">{finding.file_path}</span>
          ) : (
            <span>Suggested change</span>
          )}
        </div>
        <pre className="max-h-[min(70vh,480px)] overflow-auto p-4 text-xs leading-relaxed text-green-300/90">{mode.text}</pre>
      </div>
    )
  }

  if (identicalSides) {
    return (
      <div className="overflow-hidden rounded-md border border-amber-900/35 bg-[#0d1117] shadow-inner">
        <div className="flex flex-wrap items-center gap-2 border-b border-amber-900/25 bg-[#161b22] px-3 py-2">
          <svg className="h-4 w-4 shrink-0 text-amber-500/90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
            />
          </svg>
          <span className="min-w-0 truncate font-mono text-[12px] font-medium text-blue-300">
            {finding.file_path ?? 'files changed'}
          </span>
          <span className="rounded bg-amber-950/80 px-1.5 py-0.5 text-[10px] font-medium text-amber-200/95">No diff</span>
        </div>
        <div className="border-b border-amber-900/25 bg-amber-950/35 px-3 py-2.5 text-[11px] leading-relaxed text-amber-50/95">
          <p className="font-medium text-amber-100">Current and suggested code are the same</p>
          <p className="mt-1 text-amber-100/85">
            There is no line-by-line change to apply. The finding may be a false positive, or the code may
            already match what we would suggest.
          </p>
        </div>
        <div className="flex max-h-[min(70vh,560px)] flex-col overflow-auto md:max-h-[min(75vh,640px)] md:flex-row">
          <LineColumn label="Code" lines={mode.left} startLine={startLeft} variant="neutral" />
        </div>
        {suggestion && mode.kind === 'before_after' && !mode.rightFromSuggestion && (
          <p className="border-t border-gray-800 bg-[#0d1117] px-3 py-2 text-[11px] leading-relaxed text-gray-400">{suggestion}</p>
        )}
      </div>
    )
  }

  const { add, del } = mode.stats
  const statsLabel = add + del > 0 ? `${add > 0 ? `+${add}` : ''}${add > 0 && del > 0 ? ' ' : ''}${del > 0 ? `-${del}` : ''}`.trim() : null

  return (
    <div className="overflow-hidden rounded-md border border-gray-800 bg-[#0d1117] shadow-inner">
      {/* PR-style file header */}
      <div className="flex flex-wrap items-center gap-2 border-b border-gray-800 bg-[#161b22] px-3 py-2">
        <svg className="h-4 w-4 shrink-0 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <span className="min-w-0 truncate font-mono text-[12px] font-medium text-blue-300">
          {finding.file_path ?? 'files changed'}
        </span>
        {statsLabel && (
          <span className="rounded bg-gray-800/80 px-1.5 py-0.5 font-mono text-[10px] text-gray-400">{statsLabel}</span>
        )}
      </div>

      {mode.kind === 'before_after' && mode.rightFromSuggestion && (
        <div className="border-b border-gray-800 bg-[#161b22]/80 px-3 py-2 text-[10px] leading-snug text-gray-400">
          The suggested replacement is shown in green — it was taken from the suggestion text because no separate{' '}
          <span className="font-mono text-gray-500">code_after</span> snippet was returned.
        </div>
      )}

      {/* Side-by-side — stacks on narrow screens */}
      <div className="flex max-h-[min(70vh,560px)] flex-col overflow-auto md:max-h-[min(75vh,640px)] md:flex-row">
        <LineColumn label="Current" lines={mode.left} startLine={startLeft} variant="current" />
        <LineColumn label="Suggested" lines={mode.right} startLine={startRight} variant="suggested" />
      </div>

      {suggestion && mode.kind === 'before_after' && !mode.rightFromSuggestion && (
        <p className="border-t border-gray-800 bg-[#0d1117] px-3 py-2 text-[11px] leading-relaxed text-gray-400">{suggestion}</p>
      )}
    </div>
  )
}

/** Line counts for PR-style +N -M badge (lines that differ between before and after). */
function countChangeStats(b?: string, a?: string): { add: number; del: number } {
  const nb = (b ?? '').replace(/\r\n/g, '\n')
  const na = (a ?? '').replace(/\r\n/g, '\n')
  if (nb === na) return { add: 0, del: 0 }

  const bl = splitLines(b)
  const al = splitLines(a)
  let add = 0
  let del = 0
  const n = Math.max(bl.length, al.length)
  for (let i = 0; i < n; i++) {
    const left = bl[i]
    const right = al[i]
    if (left !== right) {
      if (left !== undefined) del += 1
      if (right !== undefined) add += 1
    }
  }
  return { add, del }
}

/** True when before/after (or parsed unified diff) has identical sides — nothing to apply. */
export function suggestedFixIsNoOp(finding: SuggestedFixFinding): boolean {
  const before = finding.code_before
  const after = finding.code_after
  const suggestion = finding.suggestion ?? ''
  if (before || after) {
    const left = splitLines(before)
    let right = splitLines(after)
    if (left.length > 0 && right.length === 0 && suggestion.trim()) {
      right = splitLines(suggestion)
    }
    return left.length > 0 && linesEqual(left, right)
  }
  const parsed = parseUnifiedDiff(suggestion)
  return !!(parsed && parsed.left.length > 0 && linesEqual(parsed.left, parsed.right))
}
