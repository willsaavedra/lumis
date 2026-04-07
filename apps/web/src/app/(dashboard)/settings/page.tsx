'use client'

import { useState, useEffect, type CSSProperties } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'next/navigation'
import { API_URL, authApi, teamApi, connectionsApi, vendorsApi, VendorConnection } from '@/lib/api'
import { useAuthStore } from '@/lib/store'
import { ObsBackendLogo } from '@/components/ObsBackendLogo'

/** JWT for full-page redirects (?token=) — must match `lumis_token` / zustand auth */
function getSessionToken(): string {
  if (typeof window === 'undefined') return ''
  const fromStore = useAuthStore.getState().token
  if (fromStore) return fromStore
  return localStorage.getItem('lumis_token') || ''
}

const VENDORS = [
  {
    value: 'datadog',
    label: 'Datadog',
    fields: [{ key: 'api_key', label: 'API Key', placeholder: 'DD app key' }],
  },
  {
    value: 'grafana',
    label: 'Grafana',
    fields: [
      { key: 'api_url', label: 'Grafana URL', placeholder: 'https://your-org.grafana.net' },
      { key: 'api_key', label: 'Service account token', placeholder: 'glsa_...' },
    ],
  },
  {
    value: 'prometheus',
    label: 'Prometheus',
    fields: [{ key: 'api_url', label: 'Prometheus URL', placeholder: 'http://prometheus:9090' }],
  },
  {
    value: 'dynatrace',
    label: 'Dynatrace',
    fields: [
      { key: 'api_url', label: 'Environment URL', placeholder: 'https://xyz.live.dynatrace.com' },
      { key: 'api_key', label: 'API Token', placeholder: 'dt0c01...' },
    ],
  },
  {
    value: 'splunk',
    label: 'Splunk',
    fields: [
      { key: 'api_url', label: 'Splunk URL', placeholder: 'https://splunk:8089' },
      { key: 'api_key', label: 'API Token', placeholder: 'Splunk token' },
    ],
  },
]

export default function SettingsPage() {
  const { membershipRole } = useAuthStore()
  const searchParams = useSearchParams()
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState<'api-keys' | 'team' | 'connections' | 'integrations'>('api-keys')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'operator' | 'viewer'>('operator')
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'error' | null>(null)

  useEffect(() => {
    const connected = searchParams.get('connected')
    const error = searchParams.get('error')
    if (connected) {
      setActiveTab('connections')
      setConnectionStatus('connected')
      // Refetch SCM connection + repo catalog (was cached before OAuth completed)
      void qc.invalidateQueries({ queryKey: ['connections'] })
      void qc.invalidateQueries({ queryKey: ['available-repos'] })
    }
    if (error) {
      setActiveTab('connections')
      setConnectionStatus('error')
    }
  }, [searchParams, qc])

  const { data: apiKeys } = useQuery({
    queryKey: ['api-keys'],
    queryFn: authApi.listApiKeys,
  })

  const { data: members } = useQuery({
    queryKey: ['team-members'],
    queryFn: teamApi.members,
  })

  const { data: connections } = useQuery({
    queryKey: ['connections'],
    queryFn: connectionsApi.list,
  })

  const { data: vendors } = useQuery({
    queryKey: ['vendors'],
    queryFn: vendorsApi.list,
  })

  const [connectingVendor, setConnectingVendor] = useState<string | null>(null)
  const [vendorFields, setVendorFields] = useState<Record<string, string>>({})

  const createVendorMutation = useMutation({
    mutationFn: (data: Parameters<typeof vendorsApi.create>[0]) => vendorsApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vendors'] })
      setConnectingVendor(null)
      setVendorFields({})
    },
  })

  const deleteVendorMutation = useMutation({
    mutationFn: vendorsApi.delete,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vendors'] }),
  })

  const createKeyMutation = useMutation({
    mutationFn: (label: string) => authApi.createApiKey(label),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })

  const revokeKeyMutation = useMutation({
    mutationFn: authApi.revokeApiKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })

  const inviteMutation = useMutation({
    mutationFn: () => teamApi.invite(inviteEmail, inviteRole),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['team-members'] })
      setInviteLink(data.invite_url)
      setInviteEmail('')
    },
  })

  const [newKeyResult, setNewKeyResult] = useState<string | null>(null)

  const card: CSSProperties = {
    border: '1px solid var(--hz-rule)',
    borderRadius: 'var(--hz-lg)',
    overflow: 'hidden',
    background: 'var(--hz-bg)',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%', background: 'var(--hz-bg)' }}>
      <div style={{ padding: '18px 24px 12px', borderBottom: '1px solid var(--hz-rule)' }}>
        <h1 className="hz-h2" style={{ margin: 0, color: 'var(--hz-ink)' }}>Settings</h1>
        <p className="hz-body" style={{ marginTop: '6px', marginBottom: 0, fontSize: '12px', color: 'var(--hz-muted)' }}>
          API access, team, Git connections, and observability integrations
        </p>
      </div>

      <div style={{ padding: '16px 24px 0', borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)' }}>
        <div className="hz-tab-nav" style={{ marginBottom: '-1px' }}>
          {(['api-keys', 'team', 'connections', 'integrations'] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`hz-tab ${activeTab === tab ? 'active' : ''}`}
            >
              {tab.replace('-', ' ')}
            </button>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, padding: '24px', maxWidth: '900px' }}>
      {/* API Keys */}
      {activeTab === 'api-keys' && (
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)' }}>
            <h2 className="hz-h2" style={{ fontSize: '14px', margin: 0, color: 'var(--hz-ink)' }}>API Keys</h2>
            <button
              type="button"
              onClick={async () => {
                const result = await createKeyMutation.mutateAsync('New Key')
                setNewKeyResult(result.api_key)
              }}
              className="hz-btn hz-btn-primary"
              style={{ fontSize: '11px', padding: '6px 12px' }}
            >
              Create key
            </button>
          </div>

          {newKeyResult && (
            <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-warn-bg)', borderLeft: '3px solid var(--hz-warn)' }}>
              <p className="hz-sm" style={{ margin: '0 0 8px', fontWeight: 500, color: 'var(--hz-warn)' }}>Save this key — it will never be shown again:</p>
              <code className="hz-term hz-scanline block p-3 rounded-md hz-sm" style={{ wordBreak: 'break-all', color: 'var(--hz-ok)' }}>{newKeyResult}</code>
              <button
                type="button"
                onClick={() => setNewKeyResult(null)}
                className="hz-sm mt-2 underline underline-offset-2"
                style={{ color: 'var(--hz-warn)', background: 'none', border: 'none', cursor: 'pointer' }}
              >
                I saved it
              </button>
            </div>
          )}

          <div>
            {(apiKeys as Array<{ id: string; label: string; key_hint: string; created_at: string }>)?.map((key, ki) => (
              <div
                key={key.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '14px 20px',
                  borderTop: ki > 0 ? '1px solid var(--hz-rule)' : undefined,
                }}
              >
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--hz-ink)' }}>{key.label}</div>
                  <div className="hz-sm" style={{ color: 'var(--hz-muted)' }}>...{key.key_hint}</div>
                </div>
                <button
                  type="button"
                  onClick={() => revokeKeyMutation.mutate(key.id)}
                  className="hz-sm"
                  style={{ color: 'var(--hz-crit)', background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  Revoke
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Team */}
      {activeTab === 'team' && (
        <div className="flex flex-col gap-4">
          {membershipRole === 'admin' && (
            <div style={{ ...card, padding: '20px' }}>
              <h3 className="hz-h2" style={{ fontSize: '13px', margin: '0 0 12px', color: 'var(--hz-ink)' }}>Invite member</h3>
              <form
                className="flex flex-col sm:flex-row gap-3 sm:items-end"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!inviteEmail.trim()) return
                  inviteMutation.mutate()
                }}
              >
                <div className="flex-1">
                  <label className="hz-label block mb-1" style={{ color: 'var(--hz-muted)' }}>Email</label>
                  <input
                    type="email"
                    required
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    className="hz-inp w-full px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="hz-label block mb-1" style={{ color: 'var(--hz-muted)' }}>Role</label>
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value as 'admin' | 'operator' | 'viewer')}
                    className="hz-inp w-full sm:w-36 px-3 py-2 text-sm capitalize"
                  >
                    <option value="viewer">Viewer</option>
                    <option value="operator">Operator</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <button
                  type="submit"
                  disabled={inviteMutation.isPending}
                  className="hz-btn hz-btn-primary disabled:opacity-50"
                  style={{ fontSize: '13px' }}
                >
                  {inviteMutation.isPending ? 'Creating…' : 'Create invite link'}
                </button>
              </form>
              {inviteLink && (
                <div className="mt-4 p-3 rounded-md hz-sm" style={{ background: 'var(--hz-bg3)', border: '1px solid var(--hz-rule)', wordBreak: 'break-all' }}>
                  <p style={{ color: 'var(--hz-muted)', margin: '0 0 6px' }}>Share this link (expires in 14 days):</p>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(inviteLink)}
                    className="text-left hover:underline"
                    style={{ color: 'var(--hz-ink)', background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px' }}
                  >
                    {inviteLink}
                  </button>
                </div>
              )}
            </div>
          )}
          {membershipRole !== 'admin' && (
            <p className="hz-body" style={{ color: 'var(--hz-muted)' }}>Only workspace admins can invite members.</p>
          )}
          <div style={card}>
            <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)' }}>
              <h2 className="hz-h2" style={{ fontSize: '14px', margin: 0, color: 'var(--hz-ink)' }}>Team Members</h2>
            </div>
            <div>
              {(members as Array<{ id: string; email: string; role: string }>)?.map((m, mi) => (
                <div
                  key={m.id}
                  style={{
                    padding: '14px 20px',
                    borderTop: mi > 0 ? '1px solid var(--hz-rule)' : undefined,
                  }}
                >
                  <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--hz-ink)' }}>{m.email}</div>
                  <div className="hz-sm capitalize" style={{ color: 'var(--hz-muted)' }}>{m.role}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Integrations */}
      {activeTab === 'integrations' && (
        <div className="flex flex-col gap-4">
          <p className="hz-body" style={{ fontSize: '13px', color: 'var(--hz-muted)' }}>
            Connect observability backends so Horion can query metrics and traces during analysis.
          </p>
          {VENDORS.map((vendor) => {
            const connected = (vendors as VendorConnection[] | undefined)?.find((v) => v.vendor === vendor.value)
            const isConnecting = connectingVendor === vendor.value

            return (
              <div key={vendor.value} style={card}>
                <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <ObsBackendLogo backend={vendor.value} className="shrink-0" imageClassName="h-6 w-6" />
                    <div className="min-w-0">
                      <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--hz-ink)' }}>{vendor.label}</div>
                      {connected ? (
                        <div className="hz-sm mt-0.5" style={{ color: 'var(--hz-muted)' }}>
                          {connected.display_name || connected.api_url || 'Connected'}
                        </div>
                      ) : (
                        <div className="hz-sm mt-0.5" style={{ color: 'var(--hz-muted)' }}>Not connected</div>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {connected ? (
                      <>
                        <span className="hz-badge hz-badge-ok"><span className="hz-dot" />Connected</span>
                        <button
                          type="button"
                          onClick={() => deleteVendorMutation.mutate(connected.id)}
                          className="hz-sm"
                          style={{ color: 'var(--hz-crit)', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 8px' }}
                        >
                          Disconnect
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={() => {
                          if (isConnecting) {
                            setConnectingVendor(null)
                            setVendorFields({})
                          } else {
                            setConnectingVendor(vendor.value)
                            setVendorFields({})
                          }
                        }}
                        className="hz-btn hz-btn-outline"
                        style={{ fontSize: '11px', padding: '6px 12px' }}
                      >
                        {isConnecting ? 'Cancel' : 'Connect'}
                      </button>
                    )}
                  </div>
                </div>

                {isConnecting && (
                  <div style={{ padding: '16px 20px', borderTop: '1px solid var(--hz-rule)', background: 'var(--hz-bg2)' }}>
                    <div className="space-y-3">
                      {vendor.fields.map((field) => (
                        <div key={field.key}>
                          <label className="hz-label block mb-1" style={{ color: 'var(--hz-muted)' }}>{field.label}</label>
                          <input
                            type={field.key === 'api_key' ? 'password' : 'text'}
                            placeholder={field.placeholder}
                            value={vendorFields[field.key] || ''}
                            onChange={(e) => setVendorFields((f) => ({ ...f, [field.key]: e.target.value }))}
                            className="hz-inp w-full px-3 py-2 text-sm"
                          />
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          createVendorMutation.mutate({
                            vendor: vendor.value,
                            display_name: vendor.label,
                            api_key: vendorFields['api_key'] || undefined,
                            api_url: vendorFields['api_url'] || undefined,
                          })
                        }}
                        disabled={createVendorMutation.isPending}
                        className="hz-btn hz-btn-primary w-full disabled:opacity-50"
                        style={{ fontSize: '13px' }}
                      >
                        {createVendorMutation.isPending ? 'Saving...' : `Save ${vendor.label} connection`}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Connections */}
      {activeTab === 'connections' && (
        <div style={{ ...card, padding: '20px 24px' }}>
          <h2 className="hz-h2" style={{ fontSize: '15px', margin: '0 0 16px', color: 'var(--hz-ink)' }}>SCM Connections</h2>

          {connectionStatus === 'connected' && (
            <div
              className="mb-4 flex items-center gap-2 rounded-md px-4 py-3 hz-sm"
              style={{ background: 'var(--hz-ok-bg)', border: '1px solid var(--hz-ok-bd)', color: 'var(--hz-ok)' }}
            >
              Git host connected successfully.
            </div>
          )}

          {connectionStatus === 'error' && (
            <div
              className="mb-4 flex items-center gap-2 rounded-md px-4 py-3 hz-sm"
              style={{ background: 'var(--hz-crit-bg)', border: '1px solid var(--hz-crit-bd)', color: 'var(--hz-crit)' }}
            >
              <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20" aria-hidden>
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-9v4a1 1 0 002 0V9a1 1 0 00-2 0zm1-4a1 1 0 100 2 1 1 0 000-2z" clipRule="evenodd" />
              </svg>
              SCM connection failed. Please try again or check API logs.
            </div>
          )}

          {/* GitHub row */}
          <div
            className="flex flex-wrap items-center justify-between gap-3 py-3 px-4 rounded-md"
            style={{ border: '1px solid var(--hz-rule)' }}
          >
            <div className="flex items-center gap-3">
              <svg style={{ width: 24, height: 24, color: 'var(--hz-ink)' }} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
              </svg>
              <div>
                <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--hz-ink)' }}>GitHub</div>
                {(() => {
                  const gh = connections?.find((c) => c.scm_type === 'github')
                  return gh ? (
                    <div className="hz-sm" style={{ color: 'var(--hz-muted)' }}>
                      Installation {gh.installation_id}
                      {gh.org_login && <> · {gh.org_login}</>}
                    </div>
                  ) : (
                    <div className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Not connected</div>
                  )
                })()}
              </div>
            </div>
            {connections?.find((c) => c.scm_type === 'github') ? (
              <span className="hz-badge hz-badge-ok"><span className="hz-dot" />Connected</span>
            ) : (
              <button
                type="button"
                onClick={() => {
                  const token = getSessionToken()
                  window.location.href = `${API_URL}/connect/github?token=${encodeURIComponent(token)}`
                }}
                className="hz-btn hz-btn-outline"
                style={{ fontSize: '11px', padding: '6px 12px' }}
              >
                Connect
              </button>
            )}
          </div>

          {/* GitLab */}
          <div
            className="flex flex-wrap items-center justify-between gap-3 py-3 px-4 rounded-md mt-3"
            style={{ border: '1px solid var(--hz-rule)' }}
          >
            <div className="flex items-center gap-3">
              <img src="https://cdn.simpleicons.org/gitlab/FC6D26" alt="" className="w-6 h-6" />
              <div>
                <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--hz-ink)' }}>GitLab</div>
                {(() => {
                  const gl = connections?.find((c) => c.scm_type === 'gitlab')
                  return gl ? (
                    <div className="hz-sm" style={{ color: 'var(--hz-muted)' }}>
                      {gl.org_login ?? 'Connected'}
                      {gl.installation_id && <> · id {gl.installation_id}</>}
                    </div>
                  ) : (
                    <div className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Not connected (OAuth)</div>
                  )
                })()}
              </div>
            </div>
            {connections?.find((c) => c.scm_type === 'gitlab') ? (
              <span className="hz-badge hz-badge-ok"><span className="hz-dot" />Connected</span>
            ) : (
              <button
                type="button"
                onClick={() => {
                  const token = getSessionToken()
                  window.location.href = `${API_URL}/connect/gitlab?token=${encodeURIComponent(token)}`
                }}
                className="hz-btn hz-btn-outline"
                style={{ fontSize: '11px', padding: '6px 12px' }}
              >
                Connect
              </button>
            )}
          </div>

          {/* Bitbucket */}
          <div
            className="flex flex-wrap items-center justify-between gap-3 py-3 px-4 rounded-md mt-3"
            style={{ border: '1px solid var(--hz-rule)' }}
          >
            <div className="flex items-center gap-3">
              <img src="https://cdn.simpleicons.org/bitbucket/0052CC" alt="" className="w-6 h-6" />
              <div>
                <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--hz-ink)' }}>Bitbucket Cloud</div>
                {(() => {
                  const bb = connections?.find((c) => c.scm_type === 'bitbucket')
                  return bb ? (
                    <div className="hz-sm" style={{ color: 'var(--hz-muted)' }}>
                      {bb.org_login ?? 'Connected'}
                    </div>
                  ) : (
                    <div className="hz-sm" style={{ color: 'var(--hz-muted)' }}>Not connected (OAuth)</div>
                  )
                })()}
              </div>
            </div>
            {connections?.find((c) => c.scm_type === 'bitbucket') ? (
              <span className="hz-badge hz-badge-ok"><span className="hz-dot" />Connected</span>
            ) : (
              <button
                type="button"
                onClick={() => {
                  const token = getSessionToken()
                  window.location.href = `${API_URL}/connect/bitbucket?token=${encodeURIComponent(token)}`
                }}
                className="hz-btn hz-btn-outline"
                style={{ fontSize: '11px', padding: '6px 12px' }}
              >
                Connect
              </button>
            )}
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
