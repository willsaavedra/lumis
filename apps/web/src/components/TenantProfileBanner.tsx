'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi, tenantApi } from '@/lib/api'
import { useAuthStore } from '@/lib/store'

export function TenantProfileBanner() {
  const qc = useQueryClient()
  const { membershipRole } = useAuthStore()
  const [name, setName] = useState('')

  const { data: me } = useQuery({
    queryKey: ['auth-me'],
    queryFn: () => authApi.me(),
  })

  const save = useMutation({
    mutationFn: (n: string) => tenantApi.updateProfile(n),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['auth-me'] })
      qc.invalidateQueries({ queryKey: ['tenant'] })
    },
  })

  if (membershipRole !== 'admin' || !me?.needs_tenant_profile) return null

  return (
    <div
      className="px-6 py-3"
      style={{
        borderBottom: '1px solid var(--hz-warn-bd)',
        background: 'var(--hz-warn-bg)',
      }}
    >
      <div className="max-w-4xl mx-auto flex flex-col sm:flex-row sm:items-center gap-3">
        <p className="hz-body flex-1" style={{ color: 'var(--hz-warn)', margin: 0 }}>
          Please confirm your workspace display name for this organization.
        </p>
        <div className="flex flex-wrap gap-2 items-center">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Workspace name"
            className="hz-inp min-w-[200px] px-3 py-2 text-sm"
          />
          <button
            type="button"
            disabled={save.isPending || !name.trim()}
            onClick={() => save.mutate(name.trim())}
            className="hz-btn hz-btn-primary"
            style={{ fontSize: '12px', padding: '7px 14px' }}
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
