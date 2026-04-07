'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  CreditCard,
  FolderGit2,
  LayoutDashboard,
  LogOut,
  Settings,
  UserCircle,
  Zap,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/lib/store'
import { TenantProfileBanner } from '@/components/TenantProfileBanner'
import { TenantSwitcher } from '@/components/TenantSwitcher'
import { ThemeToggle } from '@/components/ThemeToggle'
import { ToastContainer } from '@/components/Toast'

const navigation: { name: string; href: string; icon: LucideIcon }[] = [
  { name: 'Dashboard',    href: '/dashboard',    icon: LayoutDashboard },
  { name: 'Analyses',     href: '/analyses',     icon: Zap },
  { name: 'Repositories', href: '/repositories', icon: FolderGit2 },
  { name: 'Billing',      href: '/billing',      icon: CreditCard },
  { name: 'Settings',     href: '/settings',     icon: Settings },
]

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const { logout, token, membershipRole, setMembershipRole } = useAuthStore()
  /** Wait for zustand persist — avoids redirect to /login before token is read from localStorage */
  const [persistReady, setPersistReady] = useState(() =>
    typeof window !== 'undefined' ? useAuthStore.persist.hasHydrated() : false,
  )

  const { data: me } = useQuery({
    queryKey: ['auth-me'],
    queryFn: () => authApi.me(),
    enabled: persistReady && !!token,
  })

  useEffect(() => {
    if (me?.membership_role) {
      setMembershipRole(me.membership_role)
    }
  }, [me?.membership_role, setMembershipRole])

  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setPersistReady(true)
      return
    }
    const unsub = useAuthStore.persist.onFinishHydration(() => setPersistReady(true))
    return unsub
  }, [])

  useEffect(() => {
    if (!persistReady) return
    if (!token) {
      router.replace('/login')
    }
  }, [persistReady, token, router])

  function handleLogout() {
    logout()
    router.push('/login')
  }

  if (!persistReady || !token) {
    return (
      <div
        className="flex h-screen items-center justify-center"
        style={{ background: 'var(--hz-bg)' }}
      >
        <span
          className="hz-cursor"
          style={{ width: '10px', height: '18px', opacity: 0.4 }}
        />
      </div>
    )
  }

  const showBilling = membershipRole === 'admin' || me?.membership_role === 'admin'
  const navItems = navigation.filter((item) => item.href !== '/billing' || showBilling)

  return (
    <div
      className="flex h-screen"
      style={{ background: 'var(--hz-bg)' }}
    >
      {/* ── Sidebar ── */}
      <aside
        className="w-60 flex flex-col"
        style={{
          background: 'var(--hz-bg2)',
          borderRight: '1px solid var(--hz-rule)',
        }}
      >
        {/* Logo */}
        <div
          className="p-5"
          style={{ borderBottom: '1px solid var(--hz-rule)' }}
        >
          <div
            style={{
              fontSize: '15px',
              fontWeight: 700,
              letterSpacing: '-0.04em',
              color: 'var(--hz-ink)',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            horion.pro<span className="hz-cursor" />
          </div>
          <p
            style={{
              fontSize: '10px',
              color: 'var(--hz-muted)',
              marginTop: '3px',
              letterSpacing: '0.02em',
            }}
          >
            Reliability Engineering Platform
          </p>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-3 flex flex-col gap-0.5">
          {navItems.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
            const Icon = item.icon
            return (
              <Link
                key={item.name}
                href={item.href}
                className="flex items-center gap-2 px-2 py-1.5 rounded-md text-xs font-medium transition-none"
                style={{
                  background: active ? 'var(--hz-bg3)' : 'transparent',
                  color: active ? 'var(--hz-ink)' : 'var(--hz-muted)',
                  fontWeight: active ? 500 : 400,
                }}
                onMouseEnter={(e) => {
                  if (!active) {
                    e.currentTarget.style.background = 'var(--hz-bg3)'
                    e.currentTarget.style.color = 'var(--hz-ink2)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (!active) {
                    e.currentTarget.style.background = 'transparent'
                    e.currentTarget.style.color = 'var(--hz-muted)'
                  }
                }}
              >
                <Icon
                  className="shrink-0"
                  style={{
                    width: '14px',
                    height: '14px',
                    opacity: active ? 1 : 0.5,
                  }}
                  strokeWidth={1.75}
                  aria-hidden
                />
                {item.name}
              </Link>
            )
          })}
        </nav>

        {/* Footer */}
        <div
          className="p-3 flex flex-col gap-0.5"
          style={{ borderTop: '1px solid var(--hz-rule)' }}
        >
          <p
            className="px-2 pt-1 pb-2"
            style={{
              fontSize: '9px',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.14em',
              color: 'var(--hz-muted)',
            }}
          >
            Account
          </p>
          <TenantSwitcher />
          <Link
            href="/profile"
            className={cn('flex items-center gap-2 px-2 py-1.5 rounded-md text-xs font-medium')}
            style={{
              background:
                pathname === '/profile' || pathname.startsWith('/profile/')
                  ? 'var(--hz-bg3)'
                  : 'transparent',
              color:
                pathname === '/profile' || pathname.startsWith('/profile/')
                  ? 'var(--hz-ink)'
                  : 'var(--hz-muted)',
            }}
            onMouseEnter={(e) => {
              if (!(pathname === '/profile' || pathname.startsWith('/profile/'))) {
                e.currentTarget.style.background = 'var(--hz-bg3)'
                e.currentTarget.style.color = 'var(--hz-ink2)'
              }
            }}
            onMouseLeave={(e) => {
              if (!(pathname === '/profile' || pathname.startsWith('/profile/'))) {
                e.currentTarget.style.background = 'transparent'
                e.currentTarget.style.color = 'var(--hz-muted)'
              }
            }}
          >
            <UserCircle
              className="shrink-0"
              style={{ width: '14px', height: '14px', opacity: 0.5 }}
              strokeWidth={1.75}
              aria-hidden
            />
            Profile
          </Link>
          <div className="flex items-center justify-between px-2 py-1.5 rounded-md">
            <span style={{ fontSize: '12px', color: 'var(--hz-muted)' }}>Theme</span>
            <ThemeToggle />
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-2 py-1.5 text-xs font-medium rounded-md"
            style={{ color: 'var(--hz-muted)', background: 'transparent' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--hz-crit)'
              e.currentTarget.style.background = 'var(--hz-bg3)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--hz-muted)'
              e.currentTarget.style.background = 'transparent'
            }}
          >
            <LogOut
              className="shrink-0"
              style={{ width: '14px', height: '14px', opacity: 0.5 }}
              strokeWidth={1.75}
              aria-hidden
            />
            Sign out
          </button>
        </div>
      </aside>

      {/* ── Main content ── */}
      <main
        className="flex-1 overflow-auto flex flex-col"
        style={{ background: 'var(--hz-bg)' }}
      >
        <TenantProfileBanner />
        <div className="flex-1">{children}</div>
      </main>

      <ToastContainer />
    </div>
  )
}
