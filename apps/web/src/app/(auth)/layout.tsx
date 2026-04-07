'use client'

import { useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/store'
import { ThemeToggle } from '@/components/ThemeToggle'

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { token } = useAuthStore()
  const [hydrated, setHydrated] = useState(false)
  const isOAuthCallback = pathname === '/callback'
  const stayOnAuthWithToken =
    isOAuthCallback || pathname === '/select-tenant' || pathname === '/invite'

  useEffect(() => {
    setHydrated(true)
  }, [])

  useEffect(() => {
    if (hydrated && token && !stayOnAuthWithToken) {
      router.replace('/dashboard')
    }
  }, [hydrated, token, router, stayOnAuthWithToken])

  if (!hydrated) {
    return (
      <div className="relative min-h-screen flex items-center justify-center" style={{ background: 'var(--hz-bg)' }}>
        <div className="hz-grid-bg pointer-events-none fixed inset-0 z-0" style={{ opacity: 0.45 }} aria-hidden />
        <div
          className="w-5 h-5 rounded-full animate-spin relative z-10"
          style={{ border: '2px solid var(--hz-rule2)', borderTopColor: 'var(--hz-ink)' }}
        />
      </div>
    )
  }

  if (token && !stayOnAuthWithToken) {
    return (
      <div className="relative min-h-screen flex items-center justify-center" style={{ background: 'var(--hz-bg)' }}>
        <div className="hz-grid-bg pointer-events-none fixed inset-0 z-0" style={{ opacity: 0.45 }} aria-hidden />
        <div
          className="w-5 h-5 rounded-full animate-spin relative z-10"
          style={{ border: '2px solid var(--hz-rule2)', borderTopColor: 'var(--hz-ink)' }}
        />
      </div>
    )
  }

  return (
    <div className="relative min-h-screen flex flex-col" style={{ background: 'var(--hz-bg)' }}>
      <div className="hz-grid-bg pointer-events-none fixed inset-0 z-0" style={{ opacity: 0.48 }} aria-hidden />
      <div className="relative z-10 flex flex-1 flex-col">
        <div className="flex justify-end px-4 pt-4 sm:px-8">
          <ThemeToggle />
        </div>
        <div className="flex flex-1 items-center justify-center px-4 pb-10 sm:px-6">
          <div className="w-full max-w-md">{children}</div>
        </div>
      </div>
    </div>
  )
}
