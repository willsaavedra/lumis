'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { authApi } from '@/lib/api'
import { getLastTenantId, useAuthStore } from '@/lib/store'
import { GoogleAuthBlock } from '@/components/GoogleAuthBlock'

export default function LoginPage() {
  const router = useRouter()
  const { setAuth } = useAuthStore()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const last = getLastTenantId()
      const data = await authApi.login(email, password, last)
      setAuth(data.access_token, data.tenant_id, data.user_id, data.membership_role)
      const pending = typeof window !== 'undefined' ? sessionStorage.getItem('hz-pending-invite') : null
      if (pending) {
        sessionStorage.removeItem('hz-pending-invite')
        router.push(`/invite?token=${encodeURIComponent(pending)}`)
        return
      }
      if (data.must_select_tenant) {
        router.push('/select-tenant')
        return
      }
      router.push('/dashboard')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Login failed. Check your credentials.')
    } finally {
      setLoading(false)
    }
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
      <div className="text-center mb-8">
        <Link href="/" className="inline-block mb-6">
          <div style={{ fontSize: '15px', fontWeight: 700, letterSpacing: '-0.04em', color: 'var(--hz-ink)' }}>
            horion.pro<span className="hz-cursor" />
          </div>
          <p className="hz-micro" style={{ color: 'var(--hz-muted)', marginTop: '4px' }}>
            Reliability Engineering Platform
          </p>
        </Link>
        <h1 className="hz-h2" style={{ margin: 0, color: 'var(--hz-ink)', fontSize: '22px', fontWeight: 600 }}>
          Welcome back
        </h1>
        <p className="hz-body" style={{ marginTop: '8px', marginBottom: 0 }}>
          Sign in to Horion
        </p>
      </div>

      <GoogleAuthBlock actionLabel="Continue with Google" />

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div
            className="rounded-md px-3 py-2.5 hz-sm"
            style={{
              background: 'var(--hz-crit-bg)',
              border: '1px solid var(--hz-crit-bd)',
              color: 'var(--hz-crit)',
            }}
          >
            {error}
          </div>
        )}
        <div>
          <label className="hz-label" style={{ display: 'block', marginBottom: '6px' }}>
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="hz-inp w-full px-3 py-2.5 text-sm"
            autoComplete="email"
          />
        </div>
        <div>
          <label className="hz-label" style={{ display: 'block', marginBottom: '6px' }}>
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="hz-inp w-full px-3 py-2.5 text-sm"
            autoComplete="current-password"
          />
        </div>
        <button type="submit" disabled={loading} className="hz-btn hz-btn-primary w-full mt-2">
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
      </form>

      <p className="hz-body text-center mt-6" style={{ marginBottom: 0 }}>
        No account?{' '}
        <Link href="/signup" style={{ color: 'var(--hz-ink)', fontWeight: 500 }} className="hover:underline underline-offset-2">
          Sign up free
        </Link>
      </p>
    </div>
  )
}
