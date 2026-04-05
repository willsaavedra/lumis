'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'next/navigation'
import { authApi, teamApi, connectionsApi, vendorsApi, VendorConnection } from '@/lib/api'
import { useAuthStore } from '@/lib/store'
import { ObsBackendLogo } from '@/components/ObsBackendLogo'

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
  const [activeTab, setActiveTab] = useState<'api-keys' | 'team' | 'connections' | 'integrations'>('api-keys')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'operator' | 'viewer'>('operator')
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'error' | null>(null)

  useEffect(() => {
    const connected = searchParams.get('connected')
    const error = searchParams.get('error')
    if (connected) { setActiveTab('connections'); setConnectionStatus('connected') }
    if (error) { setActiveTab('connections'); setConnectionStatus('error') }
  }, [searchParams])
  const qc = useQueryClient()

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

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Settings</h1>
      </div>

      {/* Tabs */}
      <div className="flex gap-4 border-b border-gray-200 dark:border-gray-700 mb-6">
        {(['api-keys', 'team', 'connections', 'integrations'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`pb-3 text-sm font-medium capitalize ${
              activeTab === tab
                ? 'border-b-2 border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100'
                : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'
            }`}
          >
            {tab.replace('-', ' ')}
          </button>
        ))}
      </div>

      {/* API Keys */}
      {activeTab === 'api-keys' && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between p-5 border-b border-gray-200 dark:border-gray-700">
            <h2 className="font-semibold text-gray-900 dark:text-gray-100">API Keys</h2>
            <button
              onClick={async () => {
                const result = await createKeyMutation.mutateAsync('New Key')
                setNewKeyResult(result.api_key)
              }}
              className="px-3 py-1.5 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg text-xs font-medium hover:bg-gray-700 dark:hover:bg-gray-300"
            >
              Create key
            </button>
          </div>

          {newKeyResult && (
            <div className="p-4 bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-100 dark:border-yellow-800">
              <p className="text-xs text-yellow-800 dark:text-yellow-400 mb-2 font-medium">Save this key — it will never be shown again:</p>
              <code className="block bg-gray-950 dark:bg-black text-green-400 p-3 rounded text-xs break-all">{newKeyResult}</code>
              <button
                onClick={() => setNewKeyResult(null)}
                className="mt-2 text-xs text-yellow-700 dark:text-yellow-500 underline"
              >
                I saved it
              </button>
            </div>
          )}

          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {(apiKeys as Array<{ id: string; label: string; key_hint: string; created_at: string }>)?.map((key) => (
              <div key={key.id} className="flex items-center justify-between p-4">
                <div>
                  <div className="text-sm font-medium text-gray-900 dark:text-gray-100">{key.label}</div>
                  <div className="text-xs text-gray-400 dark:text-gray-500">...{key.key_hint}</div>
                </div>
                <button
                  onClick={() => revokeKeyMutation.mutate(key.id)}
                  className="text-xs text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300"
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
        <div className="space-y-4">
          {membershipRole === 'admin' && (
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Invite member</h3>
              <form
                className="flex flex-col sm:flex-row gap-3 sm:items-end"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!inviteEmail.trim()) return
                  inviteMutation.mutate()
                }}
              >
                <div className="flex-1">
                  <label className="block text-xs text-gray-500 mb-1">Email</label>
                  <input
                    type="email"
                    required
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Role</label>
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value as 'admin' | 'operator' | 'viewer')}
                    className="w-full sm:w-36 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 capitalize"
                  >
                    <option value="viewer">Viewer</option>
                    <option value="operator">Operator</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <button
                  type="submit"
                  disabled={inviteMutation.isPending}
                  className="px-4 py-2 text-sm font-medium rounded-lg bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 disabled:opacity-50"
                >
                  {inviteMutation.isPending ? 'Creating…' : 'Create invite link'}
                </button>
              </form>
              {inviteLink && (
                <div className="mt-4 p-3 rounded-lg bg-gray-50 dark:bg-gray-800 text-xs break-all">
                  <p className="text-gray-500 mb-1">Share this link (expires in 14 days):</p>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(inviteLink)}
                    className="text-left text-gray-900 dark:text-gray-100 hover:underline"
                  >
                    {inviteLink}
                  </button>
                </div>
              )}
            </div>
          )}
          {membershipRole !== 'admin' && (
            <p className="text-sm text-gray-500 dark:text-gray-400">Only workspace admins can invite members.</p>
          )}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700">
            <div className="p-5 border-b border-gray-200 dark:border-gray-700">
              <h2 className="font-semibold text-gray-900 dark:text-gray-100">Team Members</h2>
            </div>
            <div className="divide-y divide-gray-100 dark:divide-gray-800">
              {(members as Array<{ id: string; email: string; role: string }>)?.map((m) => (
                <div key={m.id} className="flex items-center justify-between p-4">
                  <div>
                    <div className="text-sm font-medium text-gray-900 dark:text-gray-100">{m.email}</div>
                    <div className="text-xs text-gray-400 dark:text-gray-500 capitalize">{m.role}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Integrations */}
      {activeTab === 'integrations' && (
        <div className="space-y-4">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Connect observability backends so Lumis can query metrics and traces during analysis.
          </p>
          {VENDORS.map((vendor) => {
            const connected = (vendors as VendorConnection[] | undefined)?.find((v) => v.vendor === vendor.value)
            const isConnecting = connectingVendor === vendor.value

            return (
              <div key={vendor.value} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700">
                <div className="flex items-center justify-between px-5 py-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <ObsBackendLogo backend={vendor.value} className="shrink-0" imageClassName="h-6 w-6" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-gray-900 dark:text-gray-100">{vendor.label}</div>
                      {connected ? (
                        <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                          {connected.display_name || connected.api_url || 'Connected'}
                        </div>
                      ) : (
                        <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">Not connected</div>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {connected ? (
                      <>
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-xs font-medium text-green-700 dark:text-green-400">
                          <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                          Connected
                        </span>
                        <button
                          onClick={() => deleteVendorMutation.mutate(connected.id)}
                          className="text-xs text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 px-2"
                        >
                          Disconnect
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={() => {
                          if (isConnecting) {
                            setConnectingVendor(null)
                            setVendorFields({})
                          } else {
                            setConnectingVendor(vendor.value)
                            setVendorFields({})
                          }
                        }}
                        className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                      >
                        {isConnecting ? 'Cancel' : 'Connect'}
                      </button>
                    )}
                  </div>
                </div>

                {isConnecting && (
                  <div className="px-5 pb-5 border-t border-gray-100 dark:border-gray-800 pt-4">
                    <div className="space-y-3">
                      {vendor.fields.map((field) => (
                        <div key={field.key}>
                          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">{field.label}</label>
                          <input
                            type={field.key === 'api_key' ? 'password' : 'text'}
                            placeholder={field.placeholder}
                            value={vendorFields[field.key] || ''}
                            onChange={(e) => setVendorFields((f) => ({ ...f, [field.key]: e.target.value }))}
                            className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:border-gray-400 dark:focus:border-gray-500"
                          />
                        </div>
                      ))}
                      <button
                        onClick={() => {
                          createVendorMutation.mutate({
                            vendor: vendor.value,
                            display_name: vendor.label,
                            api_key: vendorFields['api_key'] || undefined,
                            api_url: vendorFields['api_url'] || undefined,
                          })
                        }}
                        disabled={createVendorMutation.isPending}
                        className="w-full py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50"
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
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">SCM Connections</h2>

          {connectionStatus === 'error' && (
            <div className="mb-4 flex items-center gap-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-800 dark:text-red-400">
              <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-9v4a1 1 0 002 0V9a1 1 0 00-2 0zm1-4a1 1 0 100 2 1 1 0 000-2z" clipRule="evenodd" />
              </svg>
              SCM connection failed. Please try again or check API logs.
            </div>
          )}

          {/* GitHub row */}
          <div className="flex items-center justify-between py-3 border border-gray-200 dark:border-gray-700 rounded-lg px-4">
            <div className="flex items-center gap-3">
              <svg className="w-6 h-6 text-gray-800 dark:text-gray-200" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
              </svg>
              <div>
                <div className="text-sm font-medium text-gray-900 dark:text-gray-100">GitHub</div>
                {(() => {
                  const gh = connections?.find((c) => c.scm_type === 'github')
                  return gh ? (
                    <div className="text-xs text-gray-400 dark:text-gray-500">
                      Installation {gh.installation_id}
                      {gh.org_login && <> · {gh.org_login}</>}
                    </div>
                  ) : (
                    <div className="text-xs text-gray-400 dark:text-gray-500">Not connected</div>
                  )
                })()}
              </div>
            </div>
            {connections?.find((c) => c.scm_type === 'github') ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-xs font-medium text-green-700 dark:text-green-400">
                <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                Connected
              </span>
            ) : (
              <button
                onClick={() => {
                  const token = localStorage.getItem('lumis_token') || ''
                  window.location.href = `${process.env.NEXT_PUBLIC_API_URL}/connect/github?token=${encodeURIComponent(token)}`
                }}
                className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                Connect
              </button>
            )}
          </div>

          {/* GitLab */}
          <div className="flex items-center justify-between py-3 border border-gray-200 dark:border-gray-700 rounded-lg px-4 mt-3">
            <div className="flex items-center gap-3">
              <img src="https://cdn.simpleicons.org/gitlab/FC6D26" alt="" className="w-6 h-6" />
              <div>
                <div className="text-sm font-medium text-gray-900 dark:text-gray-100">GitLab</div>
                {(() => {
                  const gl = connections?.find((c) => c.scm_type === 'gitlab')
                  return gl ? (
                    <div className="text-xs text-gray-400 dark:text-gray-500">
                      {gl.org_login ?? 'Connected'}
                      {gl.installation_id && <> · id {gl.installation_id}</>}
                    </div>
                  ) : (
                    <div className="text-xs text-gray-400 dark:text-gray-500">Not connected (OAuth)</div>
                  )
                })()}
              </div>
            </div>
            {connections?.find((c) => c.scm_type === 'gitlab') ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-xs font-medium text-green-700 dark:text-green-400">
                <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                Connected
              </span>
            ) : (
              <button
                type="button"
                onClick={() => {
                  const token = localStorage.getItem('lumis_token') || ''
                  window.location.href = `${process.env.NEXT_PUBLIC_API_URL}/connect/gitlab?token=${encodeURIComponent(token)}`
                }}
                className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                Connect
              </button>
            )}
          </div>

          {/* Bitbucket */}
          <div className="flex items-center justify-between py-3 border border-gray-200 dark:border-gray-700 rounded-lg px-4 mt-3">
            <div className="flex items-center gap-3">
              <img src="https://cdn.simpleicons.org/bitbucket/0052CC" alt="" className="w-6 h-6" />
              <div>
                <div className="text-sm font-medium text-gray-900 dark:text-gray-100">Bitbucket Cloud</div>
                {(() => {
                  const bb = connections?.find((c) => c.scm_type === 'bitbucket')
                  return bb ? (
                    <div className="text-xs text-gray-400 dark:text-gray-500">
                      {bb.org_login ?? 'Connected'}
                    </div>
                  ) : (
                    <div className="text-xs text-gray-400 dark:text-gray-500">Not connected (OAuth)</div>
                  )
                })()}
              </div>
            </div>
            {connections?.find((c) => c.scm_type === 'bitbucket') ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-xs font-medium text-green-700 dark:text-green-400">
                <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                Connected
              </span>
            ) : (
              <button
                type="button"
                onClick={() => {
                  const token = localStorage.getItem('lumis_token') || ''
                  window.location.href = `${process.env.NEXT_PUBLIC_API_URL}/connect/bitbucket?token=${encodeURIComponent(token)}`
                }}
                className="px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded-lg text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                Connect
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
