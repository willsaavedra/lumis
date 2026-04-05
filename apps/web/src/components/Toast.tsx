'use client'

import { useEffect, useState } from 'react'

export interface ToastMessage {
  id: number
  message: string
  type: 'success' | 'error' | 'info'
}

let _id = 0
let _setToasts: ((fn: (prev: ToastMessage[]) => ToastMessage[]) => void) | null = null

export function toast(message: string, type: ToastMessage['type'] = 'info') {
  if (_setToasts) {
    const id = ++_id
    _setToasts((prev) => [...prev, { id, message, type }])
    setTimeout(() => {
      _setToasts?.((prev) => prev.filter((t) => t.id !== id))
    }, 4000)
  }
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  useEffect(() => {
    _setToasts = setToasts
    return () => { _setToasts = null }
  }, [])

  if (!toasts.length) return null

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`px-4 py-3 rounded-lg text-sm shadow-lg border flex items-center gap-2 ${
            t.type === 'success'
              ? 'bg-white dark:bg-gray-900 border-green-200 dark:border-green-800 text-green-700 dark:text-green-400'
              : t.type === 'error'
              ? 'bg-white dark:bg-gray-900 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400'
              : 'bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300'
          }`}
        >
          <span className="w-1.5 h-1.5 rounded-full shrink-0 ${
            t.type === 'success' ? 'bg-green-500' : t.type === 'error' ? 'bg-red-500' : 'bg-gray-400'
          }" />
          {t.message}
        </div>
      ))}
    </div>
  )
}
