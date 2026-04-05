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
    <div className="border-b border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-950/40 px-6 py-3">
      <div className="max-w-4xl mx-auto flex flex-col sm:flex-row sm:items-center gap-3">
        <p className="text-sm text-amber-900 dark:text-amber-100 flex-1">
          Please confirm your workspace display name for this organization.
        </p>
        <div className="flex gap-2 items-center">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Workspace name"
            className="px-3 py-1.5 text-sm rounded-lg border border-amber-300 dark:border-amber-800 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 min-w-[200px]"
          />
          <button
            type="button"
            disabled={save.isPending || !name.trim()}
            onClick={() => save.mutate(name.trim())}
            className="px-3 py-1.5 text-sm font-medium rounded-lg bg-amber-800 dark:bg-amber-700 text-white disabled:opacity-50"
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
