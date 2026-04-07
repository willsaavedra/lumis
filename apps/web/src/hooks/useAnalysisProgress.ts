'use client'

import { useEffect, useState, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { streamAnalysisProgress, type AnalysisProgressEvent } from '@/lib/api'

const MAX_TIMELINE = 500

/**
 * Subscribes to SSE progress for a running/pending analysis job.
 * Invalidates `['analysis', jobId]` when stage is `done` or `failed`.
 */
export function useAnalysisProgress(jobId: string | undefined, enabled: boolean) {
  const qc = useQueryClient()
  const [events, setEvents] = useState<AnalysisProgressEvent[]>([])
  const [latest, setLatest] = useState<AnalysisProgressEvent | null>(null)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const seenTerminal = useRef(false)

  useEffect(() => {
    seenTerminal.current = false
    if (!jobId || !enabled) {
      setEvents([])
      setLatest(null)
      setStreamError(null)
      setStreaming(false)
      return
    }

    const ac = new AbortController()
    setEvents([])
    setLatest(null)
    setStreamError(null)
    setStreaming(true)

    ;(async () => {
      try {
        await streamAnalysisProgress(
          jobId,
          (e) => {
            setLatest(e)
            setEvents((prev) => {
              const next = [...prev, e]
              return next.length > MAX_TIMELINE ? next.slice(-MAX_TIMELINE) : next
            })
            if (e.stage === 'done' || e.stage === 'failed') {
              seenTerminal.current = true
              qc.invalidateQueries({ queryKey: ['analysis', jobId] })
            }
          },
          { signal: ac.signal },
        )
      } catch (err: unknown) {
        if (ac.signal.aborted) return
        setStreamError(err instanceof Error ? err.message : 'Stream error')
      } finally {
        if (!ac.signal.aborted) setStreaming(false)
      }
    })()

    return () => {
      ac.abort()
    }
  }, [jobId, enabled, qc])

  return {
    progressEvents: events,
    latestProgress: latest,
    streamError,
    streaming,
    streamHealthy: streaming && !streamError,
  }
}
