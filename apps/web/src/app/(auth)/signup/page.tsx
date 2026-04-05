'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/lib/store'
import { GoogleAuthBlock } from '@/components/GoogleAuthBlock'

export default function SignupPage() {
  const router = useRouter()
  const { setAuth } = useAuthStore()
  const [form, setForm] = useState({ email: '', password: '', company_name: '' })
  const [inviteToken, setInviteToken] = useState<string | undefined>(undefined)
  const [apiKey, setApiKey] = useState<string | null>(null)
  const [mustSelectTenant, setMustSelectTenant] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('invite_token')
    if (t) setInviteToken(t)
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await authApi.signup({
        ...form,
        ...(inviteToken ? { invite_token: inviteToken } : {}),
      })
      setApiKey(data.api_key)
      const loginData = await authApi.login(form.email, form.password)
      setMustSelectTenant(loginData.must_select_tenant)
      setAuth(loginData.access_token, loginData.tenant_id, loginData.user_id, loginData.membership_role)
      if (typeof window !== 'undefined') {
        localStorage.setItem('lumis_api_key', data.api_key)
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Signup failed. Try again.')
    } finally {
      setLoading(false)
    }
  }

  if (apiKey) {
    return (
      <div className="bg-white dark:bg-gray-900 p-8 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="text-center mb-6">
          <div className="w-12 h-12 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-green-600 dark:text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Account created!</h2>
          <p className="text-gray-500 dark:text-gray-400 mt-1 text-sm">Save your API key — it will never be shown again.</p>
        </div>
        <div className="bg-gray-950 dark:bg-black rounded-lg p-4 text-sm text-green-400 break-all mb-4">
          {apiKey}
        </div>
        <button
          onClick={() => { navigator.clipboard.writeText(apiKey) }}
          className="w-full py-2 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 text-sm font-medium mb-3"
        >
          Copy to clipboard
        </button>
        <button
          onClick={() =>
            mustSelectTenant ? router.push('/select-tenant') : router.push('/dashboard?onboarding=true')
          }
          className="w-full py-2.5 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg font-medium hover:bg-gray-700 dark:hover:bg-gray-300"
        >
          I saved it — Continue
        </button>
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-900 p-8 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
      <div className="text-center mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Get started free</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">50 free credits every month</p>
      </div>

      <GoogleAuthBlock actionLabel="Sign up with Google" />

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="p-3 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded-lg text-sm border border-red-200 dark:border-red-800">
            {error}
          </div>
        )}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Workspace name</label>
          <input
            type="text"
            value={form.company_name}
            onChange={(e) => setForm({ ...form, company_name: e.target.value })}
            required
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-brand-500 outline-none"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Work email</label>
          <input
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            required
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-brand-500 outline-none"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Password</label>
          <input
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
            minLength={8}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-brand-500 outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full py-2.5 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Creating account...' : 'Create free account'}
        </button>
      </form>

      <p className="text-center text-sm text-gray-500 dark:text-gray-400 mt-6">
        Already have an account?{' '}
        <Link href="/login" className="text-gray-900 dark:text-gray-100 hover:underline font-medium">
          Sign in
        </Link>
      </p>
    </div>
  )
}
