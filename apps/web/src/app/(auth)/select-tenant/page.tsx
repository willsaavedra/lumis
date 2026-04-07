'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
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
      <div
        className="rounded-lg p-10 flex flex-col items-center justify-center min-h-[120px]"
        style={{
          background: 'var(--hz-bg)',
          border: '1px solid var(--hz-rule)',
          borderRadius: 'var(--hz-lg)',
        }}
      >
        <span
          className="inline-block rounded-full animate-spin"
          style={{
            width: '28px',
            height: '28px',
            border: '2px solid var(--hz-rule2)',
            borderTopColor: 'var(--hz-ink)',
          }}
        />
      </div>
    )
  }

  return (
    <div
      className="rounded-lg p-8 sm:p-10"
      style={{
        background: 'var(--hz-bg)',
        border: '1px solid var(--hz-rule)',
        borderRadius: 'var(--hz-lg)',
      }}
    >
      <div className="text-center mb-6">
        <Link href="/" className="inline-block mb-5">
          <div style={{ fontSize: '15px', fontWeight: 700, letterSpacing: '-0.04em', color: 'var(--hz-ink)' }}>
            horion.pro<span className="hz-cursor" />
          </div>
          <p className="hz-micro" style={{ color: 'var(--hz-muted)', marginTop: '4px' }}>
            Reliability Engineering Platform
          </p>
        </Link>
        <h1 className="hz-h2" style={{ margin: 0, color: 'var(--hz-ink)', fontSize: '22px', fontWeight: 600 }}>
          Choose a workspace
        </h1>
        <p className="hz-body" style={{ marginTop: '8px', marginBottom: 0 }}>
          You belong to more than one organization.
        </p>
      </div>

      {error && (
        <div
          className="rounded-md px-3 py-2.5 hz-sm mb-4"
          style={{
            background: 'var(--hz-crit-bg)',
            border: '1px solid var(--hz-crit-bd)',
            color: 'var(--hz-crit)',
          }}
        >
          {error}
        </div>
      )}

      <ul className="space-y-2">
        {tenants.map((t) => (
          <li key={t.tenant_id}>
            <button
              type="button"
              disabled={switching !== null}
              onClick={() => choose(t.tenant_id)}
              className="w-full text-left rounded-md px-4 py-3 transition-opacity disabled:opacity-45 hz-btn hz-btn-ghost"
              style={{
                borderColor: 'var(--hz-rule)',
                background: 'var(--hz-bg2)',
              }}
            >
              <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--hz-ink)' }}>{t.name}</div>
              <div className="hz-sm capitalize mt-0.5">{t.role}</div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
