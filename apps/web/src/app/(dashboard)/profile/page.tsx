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
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%', background: 'var(--hz-bg)' }}>
      <div style={{ padding: '18px 24px 16px', borderBottom: '1px solid var(--hz-rule)' }}>
        <h1 className="hz-h2" style={{ margin: 0, color: 'var(--hz-ink)' }}>Profile</h1>
        <p className="hz-body" style={{ marginTop: '6px', marginBottom: 0, fontSize: '12px', color: 'var(--hz-muted)' }}>
          Your account and organization details
        </p>
      </div>

      <div style={{ flex: 1, padding: '24px', maxWidth: '42rem' }}>
        <div
          style={{
            border: '1px solid var(--hz-rule)',
            borderRadius: 'var(--hz-lg)',
            overflow: 'hidden',
            background: 'var(--hz-bg)',
          }}
        >
          <div
            style={{
              padding: '20px 24px',
              borderBottom: '1px solid var(--hz-rule)',
              background: 'var(--hz-bg2)',
              display: 'flex',
              alignItems: 'center',
              gap: '16px',
            }}
          >
            <div
              style={{
                width: '56px',
                height: '56px',
                borderRadius: '50%',
                background: 'var(--hz-bg4)',
                border: '1px solid var(--hz-rule)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <UserCircle style={{ width: 28, height: 28, color: 'var(--hz-muted)' }} strokeWidth={1.25} />
            </div>
            <div>
              <p style={{ fontSize: '16px', fontWeight: 600, margin: 0, color: 'var(--hz-ink)' }}>
                {isLoading ? 'Loading…' : tenant?.name ?? 'Organization'}
              </p>
              <p className="hz-sm" style={{ marginTop: '4px', marginBottom: 0, color: 'var(--hz-muted)' }}>
                {tenant?.slug ? `@${tenant.slug}` : '—'}
              </p>
            </div>
          </div>

          <dl style={{ margin: 0 }}>
            <div
              style={{
                display: 'flex',
                gap: '16px',
                padding: '14px 24px',
                borderBottom: '1px solid var(--hz-rule)',
                flexWrap: 'wrap',
              }}
            >
              <dt
                className="hz-sm"
                style={{
                  width: '140px',
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  color: 'var(--hz-muted)',
                  margin: 0,
                }}
              >
                <Fingerprint style={{ width: 14, height: 14, marginTop: 2, flexShrink: 0 }} />
                User ID
              </dt>
              <dd
                style={{
                  margin: 0,
                  fontSize: '12px',
                  fontFamily: 'inherit',
                  color: 'var(--hz-ink)',
                  wordBreak: 'break-all',
                  flex: 1,
                  minWidth: 0,
                }}
              >
                {userId ?? '—'}
              </dd>
            </div>
            <div
              style={{
                display: 'flex',
                gap: '16px',
                padding: '14px 24px',
                borderBottom: '1px solid var(--hz-rule)',
                flexWrap: 'wrap',
              }}
            >
              <dt
                className="hz-sm"
                style={{
                  width: '140px',
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  color: 'var(--hz-muted)',
                  margin: 0,
                }}
              >
                <Building2 style={{ width: 14, height: 14, marginTop: 2, flexShrink: 0 }} />
                Tenant ID
              </dt>
              <dd
                style={{
                  margin: 0,
                  fontSize: '12px',
                  fontFamily: 'inherit',
                  color: 'var(--hz-ink)',
                  wordBreak: 'break-all',
                  flex: 1,
                  minWidth: 0,
                }}
              >
                {tenantId ?? '—'}
              </dd>
            </div>
            <div
              style={{
                display: 'flex',
                gap: '16px',
                padding: '14px 24px',
                borderBottom: '1px solid var(--hz-rule)',
                flexWrap: 'wrap',
              }}
            >
              <dt
                className="hz-sm"
                style={{
                  width: '140px',
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  color: 'var(--hz-muted)',
                  margin: 0,
                }}
              >
                <KeyRound style={{ width: 14, height: 14, marginTop: 2, flexShrink: 0 }} />
                Plan
              </dt>
              <dd style={{ margin: 0, fontSize: '13px', color: 'var(--hz-ink)', textTransform: 'capitalize' }}>
                {isError ? 'Unable to load' : tenant?.plan ?? '—'}
              </dd>
            </div>
            <div
              style={{
                display: 'flex',
                gap: '16px',
                padding: '14px 24px',
                borderBottom: '1px solid var(--hz-rule)',
                flexWrap: 'wrap',
              }}
            >
              <dt
                className="hz-sm"
                style={{
                  width: '140px',
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  color: 'var(--hz-muted)',
                  margin: 0,
                }}
              >
                <CreditCard style={{ width: 14, height: 14, marginTop: 2, flexShrink: 0 }} />
                Credits
              </dt>
              <dd style={{ margin: 0, fontSize: '13px', color: 'var(--hz-ink)' }}>
                {tenant
                  ? `${tenant.credits_remaining} remaining · ${tenant.credits_monthly_limit} monthly limit`
                  : isLoading
                    ? '…'
                    : '—'}
              </dd>
            </div>
          </dl>

          <div
            style={{
              padding: '16px 24px',
              background: 'var(--hz-bg2)',
              borderTop: '1px solid var(--hz-rule)',
              display: 'flex',
              flexWrap: 'wrap',
              gap: '10px',
            }}
          >
            <Link href="/settings" className="hz-btn hz-btn-outline inline-flex items-center gap-2">
              <Settings style={{ width: 16, height: 16 }} />
              Settings
            </Link>
            <Link href="/billing" className="hz-btn hz-btn-outline inline-flex items-center gap-2">
              <CreditCard style={{ width: 16, height: 16 }} />
              Billing
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
