'use client'

import { toast } from '@/components/Toast'
import { billingApi } from '@/lib/api'
import { useAuthStore } from '@/lib/store'
import { formatDate } from '@/lib/utils'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState } from 'react'

const PLANS = [
  { id: 'starter', name: 'Starter', price: '$49/mo', credits: '300 credits/month', overage: '$0.35/credit' },
  { id: 'growth', name: 'Growth', price: '$149/mo', credits: '1,000 credits/month', overage: '$0.25/credit' },
  { id: 'scale', name: 'Scale', price: '$449/mo', credits: '5,000 credits/month', overage: '$0.15/credit' },
]

const EVENT_LABELS: Record<string, string> = {
  reserved: 'Reserved',
  consumed: 'Credits consumed',
  released: 'Credits released',
  upgraded: 'Upgraded',
  subscription_started: 'Subscription started',
  period_renewed: 'Period renewed',
  payment_failed: 'Payment failed',
  subscription_canceled: 'Subscription canceled',
  overage_reported: 'Overage reported',
  wallet_credited: 'Wallet top-up',
}

const TOPUP_PRESETS = [10, 25, 50]

function BillingContent() {
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const { membershipRole } = useAuthStore()
  const isAdmin = membershipRole === 'admin'

  const upgraded = searchParams.get('upgrade') === 'success'
  const topupOk = searchParams.get('topup') === 'success'
  const topupCancelled = searchParams.get('topup') === 'cancelled'

  const [topupAmount, setTopupAmount] = useState(25)

  useEffect(() => {
    if (topupOk) {
      void queryClient.invalidateQueries({ queryKey: ['billing-usage'] })
      void queryClient.invalidateQueries({ queryKey: ['billing-history'] })
    }
  }, [topupOk, queryClient])

  const { data: usage } = useQuery({ queryKey: ['billing-usage'], queryFn: billingApi.usage })
  const { data: history } = useQuery({ queryKey: ['billing-history'], queryFn: billingApi.history })

  const checkoutMutation = useMutation({
    mutationFn: (plan: string) => billingApi.checkout(plan),
    onSuccess: (data) => {
      window.location.href = data.checkout_url
    },
  })

  const portalMutation = useMutation({
    mutationFn: billingApi.portal,
    onSuccess: (data) => {
      window.location.href = data.portal_url
    },
  })

  const topUpMutation = useMutation({
    mutationFn: (amount_usd: number) => billingApi.topUp({ amount_usd }),
    onSuccess: (data) => {
      window.location.href = data.checkout_url
    },
    onError: (err: unknown) => {
      const detail =
        axios.isAxiosError(err) && typeof err.response?.data?.detail === 'string'
          ? err.response.data.detail
          : 'Could not start checkout. Try again.'
      toast(detail, 'error')
    },
  })

  const creditPct = usage
    ? Math.round((usage.credits_used / Math.max(1, usage.credits_included)) * 100)
    : 0
  const currentPlan = usage?.plan || 'free'
  const rate = usage?.overage_rate_per_credit ?? 0.35
  const extraUsd = usage?.extra_balance_usd ?? 0
  const approxExtraCredits = rate > 0 ? Math.floor(extraUsd / rate) : 0

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Billing</h1>
        <p className="text-gray-500 dark:text-gray-400">Manage your subscription and credits</p>
      </div>

      {upgraded && (
        <div className="mb-6 p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl text-green-700 dark:text-green-400 text-sm">
          Upgrade successful! Your credits have been reset.
        </div>
      )}

      {topupOk && (
        <div className="mb-6 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl text-amber-800 dark:text-amber-200 text-sm">
          Extra balance added — your wallet has been updated.
        </div>
      )}

      {topupCancelled && (
        <div className="mb-6 p-4 bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-xl text-gray-600 dark:text-gray-400 text-sm">
          Payment was cancelled. No charges were made.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        {/* A: Plan + included credits */}
        <div className="bg-white dark:bg-gray-900 p-6 rounded-xl border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-gray-900 dark:text-gray-100">Current plan</h2>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium capitalize px-3 py-1 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-full">
                {currentPlan}
              </span>
              {usage?.stripe_status && usage.stripe_status !== 'active' && (
                <span className="text-xs text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/20 px-2 py-0.5 rounded">
                  {usage.stripe_status}
                </span>
              )}
            </div>
          </div>

          <h3 className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
            Included credits
          </h3>
          <div className="mb-4">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-gray-500 dark:text-gray-400">Credits used</span>
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {usage?.credits_used ?? '—'} / {usage?.credits_included ?? '—'}
              </span>
            </div>
            <div className="h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
              <div
                className={`h-2 rounded-full ${creditPct > 80 ? 'bg-orange-500' : 'bg-brand-500'}`}
                style={{ width: `${Math.min(100, creditPct)}%` }}
              />
            </div>
            {(usage?.overage_credits ?? 0) > 0 && (
              <p className="text-xs text-orange-600 dark:text-orange-400 mt-1">
                {usage?.overage_credits} overage credits — estimated ${usage?.estimated_overage_cost.toFixed(2)} on
                your invoice
              </p>
            )}
          </div>

          {usage?.period_end && (
            <p className="text-xs text-gray-400 dark:text-gray-500">Period ends {formatDate(usage.period_end)}</p>
          )}

          {currentPlan !== 'free' && (
            <button
              type="button"
              onClick={() => portalMutation.mutate()}
              disabled={portalMutation.isPending}
              className="mt-4 w-full py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 font-medium text-gray-700 dark:text-gray-300"
            >
              Manage subscription
            </button>
          )}
        </div>

        {/* B: Extra USD balance */}
        <div className="bg-white dark:bg-gray-900 p-6 rounded-xl border border-gray-200 dark:border-gray-700">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100 mb-1">Extra balance (USD)</h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
            Used after your monthly included credits run out in the current period, at your plan&apos;s per-credit
            overage rate.
          </p>
          <p className="text-3xl font-semibold text-gray-900 dark:text-gray-100 mb-1">
            {usage ? `$${extraUsd.toFixed(2)}` : '—'}
          </p>
          {usage && rate > 0 && (
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
              ≈ {approxExtraCredits} extra credits at ${rate.toFixed(2)}/credit
            </p>
          )}

          {isAdmin ? (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {TOPUP_PRESETS.map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setTopupAmount(n)}
                    className={`px-3 py-1.5 rounded-lg text-sm border ${
                      topupAmount === n
                        ? 'border-brand-500 bg-brand-50 dark:bg-brand-900/20 text-brand-800 dark:text-brand-200'
                        : 'border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300'
                    }`}
                  >
                    ${n}
                  </button>
                ))}
              </div>
              <label className="block text-xs text-gray-500 dark:text-gray-400">
                Amount (USD)
                <input
                  type="number"
                  min={5}
                  max={500}
                  step={1}
                  value={topupAmount}
                  onChange={(e) => setTopupAmount(Number(e.target.value))}
                  className="mt-1 w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-sm"
                />
              </label>
              <button
                type="button"
                onClick={() => topUpMutation.mutate(topupAmount)}
                disabled={topUpMutation.isPending || topupAmount < 5 || topupAmount > 500}
                className="w-full py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50"
              >
                {topUpMutation.isPending ? 'Redirecting…' : 'Add balance'}
              </button>
            </div>
          ) : (
            <p className="text-xs text-gray-400 dark:text-gray-500">Only tenant admins can add balance.</p>
          )}
        </div>

        {/* C: Upgrade */}
        <div className="bg-white dark:bg-gray-900 p-6 rounded-xl border border-gray-200 dark:border-gray-700">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Upgrade plan</h2>
          <div className="space-y-3">
            {PLANS.filter((p) => p.id !== currentPlan).map((plan) => (
              <div
                key={plan.id}
                className="flex items-center justify-between p-3 border border-gray-200 dark:border-gray-700 rounded-lg"
              >
                <div>
                  <div className="font-medium text-sm text-gray-900 dark:text-gray-100">
                    {plan.name} — {plan.price}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {plan.credits} · {plan.overage} overage
                  </div>
                </div>
                {isAdmin ? (
                  <button
                    type="button"
                    onClick={() => checkoutMutation.mutate(plan.id)}
                    disabled={checkoutMutation.isPending}
                    className="px-3 py-1.5 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg text-xs font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50"
                  >
                    Upgrade
                  </button>
                ) : (
                  <span className="text-xs text-gray-400">Admin only</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Billing history */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700">
        <div className="p-5 border-b border-gray-200 dark:border-gray-700">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100">Billing history</h2>
        </div>
        <div className="divide-y divide-gray-100 dark:divide-gray-800">
          {(
            history as Array<{
              id: string
              event_type: string
              credits_delta: number
              usd_amount: number
              description: string
              created_at: string
            }>
          )?.map((e) => (
            <div key={e.id} className="flex items-center justify-between px-5 py-3 text-sm">
              <div>
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {EVENT_LABELS[e.event_type] ?? e.event_type.replace(/_/g, ' ')}
                </span>
                {e.description && (
                  <span className="text-gray-400 dark:text-gray-500 ml-2">— {e.description}</span>
                )}
              </div>
              <div className="text-right">
                {e.credits_delta !== 0 && (
                  <span
                    className={
                      e.credits_delta > 0
                        ? 'text-green-600 dark:text-green-400'
                        : 'text-red-500 dark:text-red-400'
                    }
                  >
                    {e.credits_delta > 0 ? '+' : ''}
                    {e.credits_delta} credits
                  </span>
                )}
                {e.usd_amount > 0 && (
                  <span className="text-gray-500 dark:text-gray-400 ml-2">${e.usd_amount.toFixed(2)}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function BillingPage() {
  return (
    <Suspense fallback={<div className="p-8 text-gray-400 dark:text-gray-500">Loading...</div>}>
      <BillingContent />
    </Suspense>
  )
}
