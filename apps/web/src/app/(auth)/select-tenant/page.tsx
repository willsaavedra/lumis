'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { authApi, type TenantSummary } from '@/lib/api'
import { useAuthStore } from '@/lib/store'

export default function SelectTenantPage() {
  const router = useRouter()
  const { token, userId, setAuth } = useAuthStore()
  const [tenants, setTenants] = useState<TenantSummary[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState<string | null>(null)

  useEffect(() => {
    if (!token) {
      router.replace('/login')
      return
    }
    authApi
      .me()
      .then((m) => {
        setTenants(m.tenants)
        if (m.tenants.length <= 1) {
          router.replace('/dashboard')
        }
      })
      .catch(() => {
        setError('Could not load workspaces.')
      })
      .finally(() => setLoading(false))
  }, [token, router])

  async function choose(tenantId: string) {
    if (!userId) return
    setSwitching(tenantId)
    setError('')
    try {
      const r = await authApi.switchTenant(tenantId)
      setAuth(r.access_token, r.tenant_id, userId, r.membership_role)
      router.replace('/dashboard')
    } catch {
      setError('Could not switch workspace.')
    } finally {
      setSwitching(null)
    }
  }

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-900 p-8 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 text-center">
        <div className="w-8 h-8 border-2 border-gray-300 dark:border-gray-600 border-t-gray-900 dark:border-t-gray-100 rounded-full animate-spin mx-auto" />
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-900 p-8 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
      <div className="text-center mb-6">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Choose a workspace</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">You belong to more than one organization.</p>
      </div>
      {error && (
        <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded-lg text-sm">{error}</div>
      )}
      <ul className="space-y-2">
        {tenants.map((t) => (
          <li key={t.tenant_id}>
            <button
              type="button"
              disabled={switching !== null}
              onClick={() => choose(t.tenant_id)}
              className="w-full text-left px-4 py-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
            >
              <div className="font-medium text-gray-900 dark:text-gray-100">{t.name}</div>
              <div className="text-xs text-gray-500 dark:text-gray-400 capitalize">{t.role}</div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
