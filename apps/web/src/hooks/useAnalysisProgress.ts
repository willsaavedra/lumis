'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { streamAnalysisProgress, type AnalysisProgressEvent, type AgentProgressStatus } from '@/lib/api'

const MAX_TIMELINE = 80

/**
 * Subscribes to SSE progress for a running/pending analysis job.
 * Tracks per-agent status and invalidates query when done.
 */
export function useAnalysisProgress(jobId: string | undefined, enabled: boolean) {
  const qc = useQueryClient()
  const [events, setEvents] = useState<AnalysisProgressEvent[]>([])
  const [latest, setLatest] = useState<AnalysisProgressEvent | null>(null)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [agentRoster, setAgentRoster] = useState<AgentProgressStatus[]>([])
  const [activeAgent, setActiveAgent] = useState<string | null>(null)
  const [llmText, setLlmText] = useState<string | null>(null)
  const [currentFiles, setCurrentFiles] = useState<string[]>([])
  const seenTerminal = useRef(false)

  const handleEvent = useCallback(
    (e: AnalysisProgressEvent) => {
      setLatest(e)

      if (e.llm_text != null) {
        setLlmText(e.llm_text)
      }
      if (e.current_files != null) {
        setCurrentFiles(e.current_files)
      }

      // Only push non-streaming events to the timeline log
      if (e.progress_pct >= 0) {
        setEvents((prev) => {
          const next = [...prev, e]
          return next.length > MAX_TIMELINE ? next.slice(-MAX_TIMELINE) : next
        })
      }

      if (e.agents && e.agents.length > 0) {
        setAgentRoster((prev) => {
          const map = new Map(prev.map((a) => [a.name, a]))
          for (const a of e.agents!) {
            map.set(a.name, a)
          }
          return Array.from(map.values())
        })
      }

      if (e.active_agent) {
        setActiveAgent(e.active_agent)
      }

      if (e.stage === 'done' || e.stage === 'failed') {
        seenTerminal.current = true
        setLlmText(null)
        setCurrentFiles([])
        qc.invalidateQueries({ queryKey: ['analysis', jobId] })
      }
    },
    [jobId, qc],
  )

  useEffect(() => {
    seenTerminal.current = false
    if (!jobId || !enabled) {
    setEvents([])
    setLatest(null)
    setStreamError(null)
    setStreaming(false)
    setAgentRoster([])
    setActiveAgent(null)
    setLlmText(null)
    setCurrentFiles([])
    return
  }

  const ac = new AbortController()
  setEvents([])
  setLatest(null)
  setStreamError(null)
  setStreaming(true)
  setAgentRoster([])
  setActiveAgent(null)
  setLlmText(null)
  setCurrentFiles([])

    ;(async () => {
      try {
        await streamAnalysisProgress(jobId, handleEvent, { signal: ac.signal })
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
  }, [jobId, enabled, handleEvent])

  return {
    progressEvents: events,
    latestProgress: latest,
    streamError,
    streaming,
    streamHealthy: streaming && !streamError,
    agentRoster,
    activeAgent,
    llmText,
    currentFiles,
  }
}
