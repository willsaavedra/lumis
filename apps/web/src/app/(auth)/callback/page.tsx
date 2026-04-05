'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/store'

/**
 * OAuth return URL — backend redirects here with ?token=&tenant_id=&user_id= or ?error=
 */
export default function OAuthCallbackPage() {
  const router = useRouter()
  const { setAuth } = useAuthStore()
  const [state, setState] = useState<'working' | 'error'>('working')
  const [message, setMessage] = useState('Signing you in...')

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const err = params.get('error')
    if (err) {
      setState('error')
      setMessage(err.includes(' ') ? err : err.replace(/_/g, ' '))
      return
    }
    const token = params.get('token')
    const tenantId = params.get('tenant_id')
    const userId = params.get('user_id')
    const membershipRole = params.get('membership_role')
    const mustSelect = params.get('must_select_tenant') === 'true'
    if (token && tenantId && userId) {
      setAuth(token, tenantId, userId, membershipRole || undefined)
      if (mustSelect) {
        router.replace('/select-tenant')
        return
      }
      router.replace('/dashboard')
      return
    }
    setState('error')
    setMessage('Something went wrong. Try signing in again.')
  }, [router, setAuth])

  if (state === 'working') {
    return (
      <div className="bg-white dark:bg-gray-900 p-8 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 text-center">
        <div className="w-8 h-8 border-2 border-gray-300 dark:border-gray-600 border-t-gray-900 dark:border-t-gray-100 rounded-full animate-spin mx-auto mb-4" />
        <p className="text-sm text-gray-500 dark:text-gray-400">{message}</p>
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-900 p-8 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 text-center space-y-4">
      <p className="text-sm text-red-600 dark:text-red-400">{message}</p>
      <Link
        href="/login"
        className="inline-block text-sm text-gray-900 dark:text-gray-100 font-medium hover:underline"
      >
        Back to sign in
      </Link>
    </div>
  )
}
