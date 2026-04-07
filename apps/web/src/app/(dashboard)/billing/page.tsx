'use client'

import { toast } from '@/components/Toast'
import { billingApi } from '@/lib/api'
import { useAuthStore } from '@/lib/store'
import { formatDate } from '@/lib/utils'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState, type CSSProperties } from 'react'

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

const cardShell: CSSProperties = {
  border: '1px solid var(--hz-rule)',
  borderRadius: 'var(--hz-lg)',
  background: 'var(--hz-bg)',
  overflow: 'hidden',
}

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

  const barColor = creditPct > 80 ? 'var(--hz-warn)' : 'var(--hz-ok)'

  const hist = history as Array<{
    id: string
    event_type: string
    credits_delta: number
    usd_amount: number
    description: string
    created_at: string
  }> | undefined

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%', background: 'var(--hz-bg)' }}>
      <div style={{ padding: '18px 24px 16px', borderBottom: '1px solid var(--hz-rule)' }}>
        <h1 className="hz-h2" style={{ margin: 0, color: 'var(--hz-ink)' }}>Billing</h1>
        <p className="hz-body" style={{ marginTop: '6px', marginBottom: 0, fontSize: '12px', color: 'var(--hz-muted)' }}>
          Subscription, included credits, and usage history
        </p>
      </div>

      {/* Mini stats */}
      <div
        className="grid grid-cols-1 sm:grid-cols-3 gap-px"
        style={{ borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-rule)' }}
      >
        {[
          {
            label: 'Plan',
            value: currentPlan,
            sub: usage?.period_end ? `renews ${formatDate(usage.period_end)}` : 'workspace',
            accent: 'var(--hz-ink)',
          },
          {
            label: 'Credits used',
            value: usage ? `${usage.credits_used} / ${usage.credits_included}` : '—',
            sub: `${Math.min(100, creditPct)}% of period`,
            accent: creditPct > 80 ? 'var(--hz-warn)' : 'var(--hz-info)',
          },
          {
            label: 'Extra balance',
            value: usage ? `$${extraUsd.toFixed(2)}` : '—',
            sub: rate > 0 ? `overages @ $${rate.toFixed(2)}/cr` : 'wallet',
            accent: 'var(--hz-ok)',
          },
        ].map((s, i) => (
          <div
            key={i}
            style={{
              padding: '12px 20px',
              position: 'relative',
              overflow: 'hidden',
              background: 'var(--hz-bg)',
            }}
          >
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: s.accent }} />
            <div className="hz-grid-bg" style={{ position: 'absolute', inset: 0, opacity: 0.45, pointerEvents: 'none' }} />
            <div className="hz-label" style={{ marginBottom: '4px', position: 'relative', color: 'var(--hz-muted)' }}>
              {s.label}
            </div>
            <div
              style={{
                fontSize: '18px',
                fontWeight: 700,
                letterSpacing: '-0.03em',
                color: 'var(--hz-ink)',
                lineHeight: 1.2,
                position: 'relative',
                textTransform: s.label === 'Plan' ? 'capitalize' : undefined,
              }}
            >
              {s.value}
            </div>
            <div className="hz-sm" style={{ marginTop: '3px', position: 'relative' }}>
              {s.sub}
            </div>
          </div>
        ))}
      </div>

      <div style={{ flex: 1, padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        {upgraded && (
          <div
            className="hz-sm rounded-md px-4 py-3"
            style={{
              background: 'var(--hz-ok-bg)',
              border: '1px solid var(--hz-ok-bd)',
              color: 'var(--hz-ok)',
            }}
          >
            Upgrade successful — your credits have been reset for the new period.
          </div>
        )}

        {topupOk && (
          <div
            className="hz-sm rounded-md px-4 py-3"
            style={{
              background: 'var(--hz-warn-bg)',
              border: '1px solid var(--hz-warn-bd)',
              color: 'var(--hz-warn)',
            }}
          >
            Extra balance added — your wallet has been updated.
          </div>
        )}

        {topupCancelled && (
          <div
            className="hz-sm rounded-md px-4 py-3"
            style={{
              background: 'var(--hz-bg2)',
              border: '1px solid var(--hz-rule)',
              color: 'var(--hz-muted)',
            }}
          >
            Payment was cancelled. No charges were made.
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Current plan */}
          <div style={{ ...cardShell, padding: '20px' }}>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
              <h2 className="hz-h2" style={{ fontSize: '14px', margin: 0, color: 'var(--hz-ink)' }}>Current plan</h2>
              <div className="flex items-center gap-2">
                <span
                  className="hz-sm font-medium capitalize px-2.5 py-0.5 rounded-full"
                  style={{ background: 'var(--hz-bg3)', color: 'var(--hz-ink2)', border: '1px solid var(--hz-rule)' }}
                >
                  {currentPlan}
                </span>
                {usage?.stripe_status && usage.stripe_status !== 'active' && (
                  <span className="hz-badge hz-badge-warn">
                    <span className="hz-dot" />
                    {usage.stripe_status}
                  </span>
                )}
              </div>
            </div>

            <h3 className="hz-label" style={{ marginBottom: '8px', color: 'var(--hz-muted)' }}>Included credits</h3>
            <div className="mb-4">
              <div className="flex justify-between hz-sm mb-1" style={{ color: 'var(--hz-muted)' }}>
                <span>Used</span>
                <span style={{ fontWeight: 500, color: 'var(--hz-ink)' }}>
                  {usage?.credits_used ?? '—'} / {usage?.credits_included ?? '—'}
                </span>
              </div>
              <div style={{ height: '6px', background: 'var(--hz-rule)', borderRadius: '4px', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    borderRadius: '4px',
                    width: `${Math.min(100, creditPct)}%`,
                    background: barColor,
                    transition: 'width 0.4s cubic-bezier(0.4,0,0.2,1)',
                  }}
                />
              </div>
              {(usage?.overage_credits ?? 0) > 0 && (
                <p className="hz-sm mt-2" style={{ color: 'var(--hz-warn)' }}>
                  {usage?.overage_credits} overage credits — est. ${usage?.estimated_overage_cost.toFixed(2)} on invoice
                </p>
              )}
            </div>

            {usage?.period_end && (
              <p className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Period ends {formatDate(usage.period_end)}</p>
            )}

            {currentPlan !== 'free' && (
              <button
                type="button"
                onClick={() => portalMutation.mutate()}
                disabled={portalMutation.isPending}
                className="hz-btn hz-btn-outline w-full mt-4"
                style={{ fontSize: '12px' }}
              >
                {portalMutation.isPending ? 'Opening…' : 'Manage subscription'}
              </button>
            )}
          </div>

          {/* Extra balance */}
          <div style={{ ...cardShell, padding: '20px' }}>
            <h2 className="hz-h2" style={{ fontSize: '14px', margin: '0 0 4px', color: 'var(--hz-ink)' }}>
              Extra balance (USD)
            </h2>
            <p className="hz-sm mb-4" style={{ color: 'var(--hz-muted)', lineHeight: 1.5 }}>
              Used after monthly included credits run out this period, at your plan&apos;s overage rate.
            </p>
            <p style={{ fontSize: '28px', fontWeight: 600, letterSpacing: '-0.03em', color: 'var(--hz-ink)', margin: '0 0 4px' }}>
              {usage ? `$${extraUsd.toFixed(2)}` : '—'}
            </p>
            {usage && rate > 0 && (
              <p className="hz-sm mb-4" style={{ color: 'var(--hz-muted)' }}>
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
                      className="hz-sm font-medium rounded-md px-3 py-1.5"
                      style={{
                        border: `1px solid ${topupAmount === n ? 'var(--hz-ink)' : 'var(--hz-rule)'}`,
                        background: topupAmount === n ? 'var(--hz-bg3)' : 'transparent',
                        color: topupAmount === n ? 'var(--hz-ink)' : 'var(--hz-muted)',
                        cursor: 'pointer',
                      }}
                    >
                      ${n}
                    </button>
                  ))}
                </div>
                <label className="block hz-sm" style={{ color: 'var(--hz-muted)' }}>
                  Amount (USD)
                  <input
                    type="number"
                    min={5}
                    max={500}
                    step={1}
                    value={topupAmount}
                    onChange={(e) => setTopupAmount(Number(e.target.value))}
                    className="hz-inp mt-1 w-full px-3 py-2 text-sm"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => topUpMutation.mutate(topupAmount)}
                  disabled={topUpMutation.isPending || topupAmount < 5 || topupAmount > 500}
                  className="hz-btn hz-btn-primary w-full disabled:opacity-50"
                  style={{ fontSize: '13px' }}
                >
                  {topUpMutation.isPending ? 'Redirecting…' : 'Add balance'}
                </button>
              </div>
            ) : (
              <p className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Only tenant admins can add balance.</p>
            )}
          </div>

          {/* Upgrade */}
          <div style={{ ...cardShell, padding: '20px' }}>
            <h2 className="hz-h2" style={{ fontSize: '14px', margin: '0 0 12px', color: 'var(--hz-ink)' }}>Upgrade plan</h2>
            <div className="space-y-2">
              {PLANS.filter((p) => p.id !== currentPlan).map((plan) => (
                <div
                  key={plan.id}
                  className="flex flex-wrap items-center justify-between gap-2 p-3 rounded-md"
                  style={{ border: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)' }}
                >
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--hz-ink)' }}>
                      {plan.name} — {plan.price}
                    </div>
                    <div className="hz-sm" style={{ color: 'var(--hz-muted)' }}>
                      {plan.credits} · {plan.overage} overage
                    </div>
                  </div>
                  {isAdmin ? (
                    <button
                      type="button"
                      onClick={() => checkoutMutation.mutate(plan.id)}
                      disabled={checkoutMutation.isPending}
                      className="hz-btn hz-btn-primary shrink-0 disabled:opacity-50"
                      style={{ fontSize: '11px', padding: '6px 12px' }}
                    >
                      Upgrade
                    </button>
                  ) : (
                    <span className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Admin only</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Billing history */}
        <div style={cardShell}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)' }}>
            <h2 className="hz-h2" style={{ fontSize: '14px', margin: 0, color: 'var(--hz-ink)' }}>Billing history</h2>
          </div>
          <div>
            {hist?.map((e, ei) => (
              <div
                key={e.id}
                className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 hz-sm"
                style={{
                  borderTop: ei > 0 ? '1px solid var(--hz-rule)' : undefined,
                }}
              >
                <div style={{ color: 'var(--hz-ink)', minWidth: 0 }}>
                  <span style={{ fontWeight: 500 }}>
                    {EVENT_LABELS[e.event_type] ?? e.event_type.replace(/_/g, ' ')}
                  </span>
                  {e.description && (
                    <span style={{ color: 'var(--hz-muted)', marginLeft: '6px' }}>— {e.description}</span>
                  )}
                </div>
                <div className="text-right shrink-0">
                  {e.credits_delta !== 0 && (
                    <span
                      style={{
                        color: e.credits_delta > 0 ? 'var(--hz-ok)' : 'var(--hz-crit)',
                        fontWeight: 500,
                      }}
                    >
                      {e.credits_delta > 0 ? '+' : ''}
                      {e.credits_delta} credits
                    </span>
                  )}
                  {e.usd_amount > 0 && (
                    <span style={{ color: 'var(--hz-muted)', marginLeft: '8px' }}>${e.usd_amount.toFixed(2)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function BillingPage() {
  return (
    <Suspense
      fallback={(
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '200px', background: 'var(--hz-bg)' }}>
          <span className="hz-cursor" style={{ opacity: 0.35 }} aria-hidden />
        </div>
      )}
    >
      <BillingContent />
    </Suspense>
  )
}
