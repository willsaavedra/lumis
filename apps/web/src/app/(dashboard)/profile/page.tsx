'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import {
  Building2,
  CreditCard,
  Fingerprint,
  KeyRound,
  Settings,
  UserCircle,
} from 'lucide-react'
import { tenantApi } from '@/lib/api'
import { useAuthStore } from '@/lib/store'

export default function ProfilePage() {
  const { userId, tenantId } = useAuthStore()
  const { data: tenant, isLoading, isError } = useQuery({
    queryKey: ['tenant'],
    queryFn: tenantApi.get,
  })

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Profile</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Your account and organization details
        </p>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="p-6 border-b border-gray-200 dark:border-gray-800 flex items-center gap-4">
          <div className="h-16 w-16 rounded-full bg-gradient-to-br from-gray-200 to-gray-300 dark:from-gray-700 dark:to-gray-600 flex items-center justify-center">
            <UserCircle className="h-9 w-9 text-gray-600 dark:text-gray-300" strokeWidth={1.25} />
          </div>
          <div>
            <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              {isLoading ? 'Loading…' : tenant?.name ?? 'Organization'}
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {tenant?.slug ? `@${tenant.slug}` : '—'}
            </p>
          </div>
        </div>

        <dl className="divide-y divide-gray-200 dark:divide-gray-800">
          <div className="px-6 py-4 flex gap-4">
            <dt className="flex items-start gap-2 text-sm text-gray-500 dark:text-gray-400 w-40 shrink-0">
              <Fingerprint className="h-4 w-4 mt-0.5 shrink-0" />
              User ID
            </dt>
            <dd className="text-sm font-mono text-gray-900 dark:text-gray-100 break-all">
              {userId ?? '—'}
            </dd>
          </div>
          <div className="px-6 py-4 flex gap-4">
            <dt className="flex items-start gap-2 text-sm text-gray-500 dark:text-gray-400 w-40 shrink-0">
              <Building2 className="h-4 w-4 mt-0.5 shrink-0" />
              Tenant ID
            </dt>
            <dd className="text-sm font-mono text-gray-900 dark:text-gray-100 break-all">
              {tenantId ?? '—'}
            </dd>
          </div>
          <div className="px-6 py-4 flex gap-4">
            <dt className="flex items-start gap-2 text-sm text-gray-500 dark:text-gray-400 w-40 shrink-0">
              <KeyRound className="h-4 w-4 mt-0.5 shrink-0" />
              Plan
            </dt>
            <dd className="text-sm text-gray-900 dark:text-gray-100 capitalize">
              {isError ? 'Unable to load' : tenant?.plan ?? '—'}
            </dd>
          </div>
          <div className="px-6 py-4 flex gap-4">
            <dt className="flex items-start gap-2 text-sm text-gray-500 dark:text-gray-400 w-40 shrink-0">
              <CreditCard className="h-4 w-4 mt-0.5 shrink-0" />
              Credits
            </dt>
            <dd className="text-sm text-gray-900 dark:text-gray-100">
              {tenant
                ? `${tenant.credits_remaining} remaining · ${tenant.credits_monthly_limit} monthly limit`
                : isLoading
                  ? '…'
                  : '—'}
            </dd>
          </div>
        </dl>

        <div className="px-6 py-4 bg-gray-50 dark:bg-gray-950/50 border-t border-gray-200 dark:border-gray-800 flex flex-wrap gap-3">
          <Link
            href="/settings"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-white dark:hover:bg-gray-800 transition-colors"
          >
            <Settings className="h-4 w-4" />
            Settings
          </Link>
          <Link
            href="/billing"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-white dark:hover:bg-gray-800 transition-colors"
          >
            <CreditCard className="h-4 w-4" />
            Billing
          </Link>
        </div>
      </div>
    </div>
  )
}
