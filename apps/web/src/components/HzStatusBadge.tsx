'use client'

/** Semantic job status — matches Horion mini badge spec (dot + label). */
export function HzStatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { bg: string; color: string; pulse?: boolean }> = {
    completed: { bg: 'var(--hz-ok-bg)', color: 'var(--hz-ok)' },
    running: { bg: 'var(--hz-info-bg)', color: 'var(--hz-info)', pulse: true },
    pending: { bg: 'var(--hz-bg3)', color: 'var(--hz-muted)' },
    failed: { bg: 'var(--hz-crit-bg)', color: 'var(--hz-crit)' },
  }
  const c = cfg[status] ?? { bg: 'var(--hz-bg3)', color: 'var(--hz-muted)' }
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
        padding: '3px 8px',
        borderRadius: '4px',
        fontSize: '10px',
        fontWeight: 500,
        whiteSpace: 'nowrap',
        background: c.bg,
        color: c.color,
      }}
    >
      <div
        style={{
          width: '5px',
          height: '5px',
          borderRadius: '50%',
          background: c.color,
          animation: c.pulse ? 'hz-pulse 1s ease infinite' : undefined,
        }}
      />
      {status}
    </div>
  )
}
