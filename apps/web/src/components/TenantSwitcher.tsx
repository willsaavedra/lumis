'use client'

import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronUp } from 'lucide-react'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/lib/store'

export function TenantSwitcher() {
  const qc = useQueryClient()
  const { tenantId, userId, setAuth, membershipRole } = useAuthStore()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const { data: me } = useQuery({
    queryKey: ['auth-me'],
    queryFn: () => authApi.me(),
  })

  const tenants = me?.tenants ?? []

  const current = useMemo(
    () => tenants.find((t) => t.tenant_id === tenantId),
    [tenants, tenantId],
  )

  async function switchTo(nextId: string) {
    if (!userId || nextId === tenantId || busy) return
    setBusy(true)
    try {
      const r = await authApi.switchTenant(nextId)
      setAuth(r.access_token, r.tenant_id, userId, r.membership_role)
      await qc.invalidateQueries({ queryKey: ['auth-me'] })
      setOpen(false)
      window.location.reload()
    } finally {
      setBusy(false)
    }
  }

  if (!tenantId || tenants.length <= 1) return null

  return (
    <div className="relative px-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full text-left rounded-md px-2 py-1.5 transition-none"
        style={{
          background: open ? 'var(--hz-bg3)' : 'transparent',
          border: `1px solid ${open ? 'var(--hz-rule)' : 'transparent'}`,
        }}
        onMouseEnter={(e) => {
          if (!open) e.currentTarget.style.background = 'var(--hz-bg3)'
        }}
        onMouseLeave={(e) => {
          if (!open) e.currentTarget.style.background = 'transparent'
        }}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className="hz-label" style={{ display: 'block', marginBottom: '2px' }}>
          Workspace
        </span>
        <span
          className="flex items-center justify-between gap-1 min-w-0"
          style={{ fontSize: '12px', fontWeight: 500, color: 'var(--hz-ink)' }}
        >
          <span className="truncate">{current?.name ?? '—'}</span>
          <ChevronUp
            className="shrink-0"
            style={{
              width: '14px',
              height: '14px',
              color: 'var(--hz-muted)',
              transform: open ? 'rotate(0deg)' : 'rotate(180deg)',
              transition: 'transform 0.15s ease',
            }}
            strokeWidth={1.75}
            aria-hidden
          />
        </span>
        <span className="hz-sm block truncate mt-0.5 capitalize">{membershipRole || 'member'}</span>
      </button>

      {open && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-40 cursor-default"
            style={{ background: 'color-mix(in srgb, var(--hz-ink) 22%, transparent)' }}
            aria-label="Close workspace menu"
            onClick={() => setOpen(false)}
          />
          <div
            className="absolute bottom-full left-0 right-0 z-50 mb-1 max-h-52 overflow-auto"
            style={{
              background: 'var(--hz-bg)',
              border: '1px solid var(--hz-rule)',
              borderRadius: 'var(--hz-md)',
            }}
            role="listbox"
            aria-label="Switch workspace"
          >
            <ul className="py-1">
              {tenants.map((t) => {
                const active = t.tenant_id === tenantId
                return (
                  <li key={t.tenant_id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={active}
                      disabled={busy || active}
                      onClick={() => switchTo(t.tenant_id)}
                      className="w-full text-left px-3 py-2 disabled:opacity-45"
                      style={{
                        background: active ? 'var(--hz-bg3)' : 'transparent',
                        cursor: active ? 'default' : 'pointer',
                      }}
                      onMouseEnter={(e) => {
                        if (!active && !busy) {
                          e.currentTarget.style.background = 'var(--hz-bg3)'
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (!active) {
                          e.currentTarget.style.background = 'transparent'
                        }
                      }}
                    >
                      <span
                        className="block truncate"
                        style={{ fontSize: '12px', fontWeight: 500, color: 'var(--hz-ink)' }}
                      >
                        {t.name}
                      </span>
                      <span className="hz-sm capitalize">{t.role}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        </>
      )}
    </div>
  )
}
