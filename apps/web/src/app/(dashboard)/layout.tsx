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
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'Analyses', href: '/analyses', icon: Zap },
  { name: 'Repositories', href: '/repositories', icon: FolderGit2 },
  { name: 'Billing', href: '/billing', icon: CreditCard },
  { name: 'Settings', href: '/settings', icon: Settings },
]

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const { logout, token, membershipRole, setMembershipRole } = useAuthStore()
  const [hydrated, setHydrated] = useState(false)

  const { data: me } = useQuery({
    queryKey: ['auth-me'],
    queryFn: () => authApi.me(),
    enabled: hydrated && !!token,
  })

  useEffect(() => {
    if (me?.membership_role) {
      setMembershipRole(me.membership_role)
    }
  }, [me?.membership_role, setMembershipRole])

  // Wait for Zustand persist to hydrate from localStorage before checking auth
  useEffect(() => {
    setHydrated(true)
  }, [])

  useEffect(() => {
    if (hydrated && !token) {
      router.replace('/login')
    }
  }, [hydrated, token, router])

  function handleLogout() {
    logout()
    router.push('/login')
  }

  // Avoid flash of dashboard content before redirect
  if (!hydrated || !token) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50 dark:bg-gray-950">
        <div className="w-5 h-5 border-2 border-gray-300 dark:border-gray-600 border-t-gray-900 dark:border-t-gray-100 rounded-full animate-spin" />
      </div>
    )
  }

  const showBilling = membershipRole === 'admin' || me?.membership_role === 'admin'
  const navItems = navigation.filter((item) => item.href !== '/billing' || showBilling)

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-950">
      {/* Sidebar */}
      <aside className="w-60 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col">
        <div className="p-5 border-b border-gray-200 dark:border-gray-800">
          <span className="text-xl font-bold text-gray-900 dark:text-gray-100">lumis</span>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">AI-powered Observability Platform</p>
        </div>

        <nav className="flex-1 p-4 space-y-1">
          {navItems.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
            const Icon = item.icon
            return (
              <Link
                key={item.name}
                href={item.href}
                className={cn(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  active
                    ? 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                    : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100'
                )}
              >
                <Icon
                  className={cn(
                    'h-5 w-5 shrink-0',
                    active ? 'text-gray-900 dark:text-gray-100' : 'text-gray-400 dark:text-gray-500'
                  )}
                  strokeWidth={1.75}
                  aria-hidden
                />
                {item.name}
              </Link>
            )
          })}
        </nav>

        <div className="p-4 border-t border-gray-200 dark:border-gray-800 space-y-1">
          <p className="px-3 pt-1 pb-2 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
            Account
          </p>
          <TenantSwitcher />
          <Link
            href="/profile"
            className={cn(
              'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              pathname === '/profile' || pathname.startsWith('/profile/')
                ? 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-gray-100'
            )}
          >
            <UserCircle
              className={cn(
                'h-5 w-5 shrink-0',
                pathname === '/profile' || pathname.startsWith('/profile/')
                  ? 'text-gray-900 dark:text-gray-100'
                  : 'text-gray-400 dark:text-gray-500'
              )}
              strokeWidth={1.75}
              aria-hidden
            />
            Profile
          </Link>
          <div className="flex items-center justify-between px-3 py-2 rounded-lg">
            <span className="text-sm text-gray-500 dark:text-gray-400">Theme</span>
            <ThemeToggle />
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-3 py-2 text-sm font-medium text-gray-500 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <LogOut className="h-5 w-5 shrink-0 text-gray-400 dark:text-gray-500" strokeWidth={1.75} aria-hidden />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto flex flex-col">
        <TenantProfileBanner />
        <div className="flex-1">{children}</div>
      </main>

      <ToastContainer />
    </div>
  )
}
