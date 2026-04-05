'use client'

import { useState } from 'react'
import { Lightbulb, Copy, Check, ExternalLink } from 'lucide-react'
import { BadgeIcon } from '@/components/BadgeIcon'
import type { InstrumentationRecommendation } from '@/lib/instrumentation-recommendation'

const ICONS: Record<string, { src: string; invertOnDark?: boolean }> = {
  otel:        { src: 'https://cdn.simpleicons.org/opentelemetry/000000', invertOnDark: true },
  datadog:     { src: 'https://cdn.simpleicons.org/datadog/632CA6' },
  prometheus:  { src: 'https://cdn.simpleicons.org/prometheus/E6522C' },
  'datadog-k8s': { src: 'https://cdn.simpleicons.org/datadog/632CA6' },
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 p-1 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
      title="Copy"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  )
}

export function InstrumentationRecommendationCard({
  recommendation,
}: {
  recommendation: InstrumentationRecommendation
}) {
  const icon = ICONS[recommendation.type]

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-950/30 p-5">
      <div className="flex items-start gap-3">
        <Lightbulb className="h-5 w-5 shrink-0 mt-0.5 text-amber-500 dark:text-amber-400" />
        <div className="min-w-0 flex-1 space-y-3">
          <div>
            <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-200 mb-0.5">
              {recommendation.type === 'prometheus' || recommendation.type === 'datadog-k8s'
                ? 'Monitoring recommendation'
                : 'Instrumentation recommendation'}
            </h3>
            <p className="text-xs text-amber-700 dark:text-amber-300/80">{recommendation.reason}</p>
          </div>

          <div className="flex items-center gap-2">
            {icon && (
              <BadgeIcon
                title={recommendation.title}
                src={icon.src}
                invertOnDark={icon.invertOnDark}
              />
            )}
            <span className="text-sm font-medium text-amber-900 dark:text-amber-200">
              {recommendation.title}
            </span>
          </div>

          {recommendation.snippet && (
            <div className="relative">
              <pre className="text-xs bg-amber-100 dark:bg-amber-950/60 text-amber-950 dark:text-amber-100 rounded-lg px-3 py-2.5 pr-8 overflow-x-auto font-mono leading-relaxed whitespace-pre">
                {recommendation.snippet}
              </pre>
              <CopyButton text={recommendation.snippet} />
            </div>
          )}

          <a
            href={recommendation.docsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400 hover:underline"
          >
            View documentation
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </div>
    </div>
  )
}
