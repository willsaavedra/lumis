'use client'

import { Suspense, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { authApi, type InvitePreviewResponse } from '@/lib/api'
import { useAuthStore } from '@/lib/store'

function InviteInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const rawToken = searchParams.get('token')
  const { token, setAuth, userId } = useAuthStore()
  const [preview, setPreview] = useState<InvitePreviewResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [accepting, setAccepting] = useState(false)

  useEffect(() => {
    if (!rawToken) {
      setError('Missing invite token.')
      setLoading(false)
      return
    }
    authApi
      .previewInvite(rawToken)
      .then(setPreview)
      .catch(() => setError('Invite not found.'))
      .finally(() => setLoading(false))
  }, [rawToken])

  async function acceptAndSwitch() {
    if (!rawToken || !token || !userId) return
    setAccepting(true)
    setError('')
    try {
      const { tenant_id } = await authApi.acceptInvite(rawToken)
      const r = await authApi.switchTenant(tenant_id)
      setAuth(r.access_token, r.tenant_id, userId, r.membership_role)
      router.replace('/dashboard')
    } catch {
      setError('Could not accept invite.')
    } finally {
      setAccepting(false)
    }
  }

  if (loading) {
    return (
      <div className="text-center py-8">
        <div className="w-8 h-8 border-2 border-gray-300 dark:border-gray-600 border-t-gray-900 dark:border-t-gray-100 rounded-full animate-spin mx-auto" />
      </div>
    )
  }

  if (!rawToken || error) {
    return (
      <div className="text-center space-y-4">
        <p className="text-sm text-red-600 dark:text-red-400">{error || 'Invalid link.'}</p>
        <Link href="/login" className="text-sm font-medium text-gray-900 dark:text-gray-100 hover:underline">
          Sign in
        </Link>
      </div>
    )
  }

  if (!preview) return null

  if (preview.accepted) {
    return (
      <div className="text-center space-y-2">
        <p className="text-sm text-gray-600 dark:text-gray-400">This invite was already accepted.</p>
        <Link href="/dashboard" className="text-sm font-medium text-gray-900 dark:text-gray-100 hover:underline">
          Go to dashboard
        </Link>
      </div>
    )
  }

  if (preview.expired) {
    return (
      <div className="text-center space-y-2">
        <p className="text-sm text-red-600 dark:text-red-400">This invite has expired.</p>
        <Link href="/login" className="text-sm font-medium text-gray-900 dark:text-gray-100 hover:underline">
          Sign in
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Workspace invite</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
          You&apos;ve been invited to <span className="font-medium text-gray-800 dark:text-gray-200">{preview.tenant_name}</span> as{' '}
          <span className="capitalize">{preview.role}</span>.
        </p>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-2">For {preview.email}</p>
      </div>

      {!token ? (
        <div className="space-y-3 text-center">
          <p className="text-sm text-gray-600 dark:text-gray-400">Sign in with the invited email to accept.</p>
          <Link
            href="/login"
            onClick={() => rawToken && sessionStorage.setItem('lumis_pending_invite', rawToken)}
            className="inline-block w-full py-2.5 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg font-medium text-center"
          >
            Sign in to accept
          </Link>
        </div>
      ) : (
        <button
          type="button"
          disabled={accepting}
          onClick={acceptAndSwitch}
          className="w-full py-2.5 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg font-medium disabled:opacity-50"
        >
          {accepting ? 'Joining…' : 'Accept and open workspace'}
        </button>
      )}

      {error && <p className="text-sm text-red-600 dark:text-red-400 text-center">{error}</p>}
    </div>
  )
}

export default function InvitePage() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-8">
          <div className="w-8 h-8 border-2 border-gray-300 dark:border-gray-600 border-t-gray-900 dark:border-t-gray-100 rounded-full animate-spin" />
        </div>
      }
    >
      <InviteInner />
    </Suspense>
  )
}
