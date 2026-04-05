'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
    <div className="relative px-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full text-left text-xs text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 py-1"
      >
        <span className="block font-medium text-gray-900 dark:text-gray-100 truncate">Workspace</span>
        <span className="block truncate opacity-80 capitalize">{membershipRole || 'member'} · switch…</span>
      </button>
      {open && (
        <>
          <button type="button" className="fixed inset-0 z-40 cursor-default" aria-label="Close" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full left-3 right-3 mb-1 z-50 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg max-h-48 overflow-auto">
            <ul className="py-1">
              {tenants.map((t) => (
                <li key={t.tenant_id}>
                  <button
                    type="button"
                    disabled={busy || t.tenant_id === tenantId}
                    onClick={() => switchTo(t.tenant_id)}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
                  >
                    <span className="block font-medium text-gray-900 dark:text-gray-100">{t.name}</span>
                    <span className="text-xs text-gray-500 capitalize">{t.role}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  )
}
