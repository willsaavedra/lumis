'use client'

import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'

export function ThemeToggle() {
  const [dark, setDark] = useState(false)

  useEffect(() => {
    setDark(document.documentElement.classList.contains('dark'))
  }, [])

  function toggle() {
    const next = !dark
    setDark(next)
    document.documentElement.classList.toggle('dark', next)
    localStorage.setItem('hz-theme', next ? 'dark' : 'light')
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle theme"
      className="w-8 h-8 flex items-center justify-center rounded-lg"
      style={{ color: 'var(--hz-muted)', background: 'transparent' }}
      onMouseEnter={(e) => {
        e.currentTarget.style.color = 'var(--hz-ink)'
        e.currentTarget.style.background = 'var(--hz-bg3)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.color = 'var(--hz-muted)'
        e.currentTarget.style.background = 'transparent'
      }}
    >
      {dark ? (
        <Sun className="w-4 h-4" strokeWidth={1.75} aria-hidden />
      ) : (
        <Moon className="w-4 h-4" strokeWidth={1.75} aria-hidden />
      )}
    </button>
  )
}
