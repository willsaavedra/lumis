import { BadgeIcon } from '@/components/BadgeIcon'

type ObsBackendId = 'datadog' | 'grafana' | 'prometheus' | 'dynatrace' | 'splunk'

function normalizeBackend(v: string): ObsBackendId | null {
  const s = v.trim().toLowerCase().replace(/-/g, '_')
  if (s === 'datadog') return 'datadog'
  if (s === 'grafana') return 'grafana'
  if (s === 'prometheus') return 'prometheus'
  if (s === 'dynatrace') return 'dynatrace'
  if (s === 'splunk') return 'splunk'
  return null
}

const LABELS: Record<ObsBackendId, string> = {
  datadog: 'Datadog',
  grafana: 'Grafana',
  prometheus: 'Prometheus',
  dynatrace: 'Dynatrace',
  splunk: 'Splunk',
}

const COLORS: Record<ObsBackendId, string> = {
  datadog: '632CA6',
  grafana: 'F46800',
  prometheus: 'E6522C',
  dynatrace: '1496FF',
  splunk: '000000',
}

export function ObsBackendLogo({
  backend,
  className = '',
  imageClassName = 'h-4 w-4',
}: {
  backend: string
  /** Wrapper span */
  className?: string
  /** Passed to the img (e.g. h-6 w-6 for settings rows) */
  imageClassName?: string
}) {
  const id = normalizeBackend(backend)
  if (!id) return null
  const src = `https://cdn.simpleicons.org/${id}/${COLORS[id]}`
  const invertOnDark = id === 'splunk'
  return (
    <BadgeIcon
      title={LABELS[id]}
      src={src}
      invertOnDark={invertOnDark}
      className={className}
      imageClassName={imageClassName}
    />
  )
}

