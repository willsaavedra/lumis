import { Ban, Package } from 'lucide-react'
import { BadgeIcon } from '@/components/BadgeIcon'

type InstrumentationId = 'otel' | 'datadog' | 'mixed' | 'none' | 'other'

function normalizeInstrumentation(v: string): InstrumentationId {
  const s = v.trim().toLowerCase().replace(/-/g, '_')
  if (s === 'otel' || s === 'opentelemetry') return 'otel'
  if (s === 'datadog' || s === 'dd_trace' || s === 'ddtrace') return 'datadog'
  if (s === 'mixed') return 'mixed'
  if (s === 'none' || s === '') return 'none'
  if (s === 'other') return 'other'
  return 'other'
}

/** Human-readable label for repository instrumentation field. */
export function instrumentationLabel(value: string): string {
  const id = normalizeInstrumentation(value)
  const labels: Record<InstrumentationId, string> = {
    otel: 'OpenTelemetry',
    datadog: 'Datadog tracer',
    mixed: 'Mixed',
    none: 'None',
    other: 'Other',
  }
  return labels[id] ?? value.replace(/_/g, ' ')
}

/**
 * Brand / semantic icon for instrumentation type (matches repo context form options).
 */
export function InstrumentationLogo({ value }: { value: string }) {
  const id = normalizeInstrumentation(value)

  if (id === 'otel') {
    const src = 'https://cdn.simpleicons.org/opentelemetry/000000'
    return <BadgeIcon title="OpenTelemetry" src={src} invertOnDark />
  }
  if (id === 'datadog') {
    const src = 'https://cdn.simpleicons.org/datadog/632CA6'
    return <BadgeIcon title="Datadog tracer" src={src} />
  }
  if (id === 'mixed') {
    return (
      <span className="inline-flex items-center gap-0.5" title="OpenTelemetry + Datadog">
        <BadgeIcon
          title="OpenTelemetry"
          src="https://cdn.simpleicons.org/opentelemetry/000000"
          imageClassName="h-3.5 w-3.5"
          invertOnDark
        />
        <BadgeIcon
          title="Datadog"
          src="https://cdn.simpleicons.org/datadog/632CA6"
          imageClassName="h-3.5 w-3.5"
        />
      </span>
    )
  }
  if (id === 'none') {
    return (
      <span className="inline-flex h-4 w-4 items-center justify-center text-gray-400 dark:text-gray-500" title="No instrumentation">
        <Ban className="h-4 w-4" strokeWidth={1.75} aria-hidden />
      </span>
    )
  }
  return (
    <span className="inline-flex h-4 w-4 items-center justify-center text-gray-400 dark:text-gray-500" title="Other">
      <Package className="h-4 w-4" strokeWidth={1.75} aria-hidden />
    </span>
  )
}
