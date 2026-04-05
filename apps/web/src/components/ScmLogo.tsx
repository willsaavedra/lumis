/**
 * SCM provider logo (matches API scm_type: github | gitlab | bitbucket | azure_devops).
 */
export type ScmTypeId = 'github' | 'gitlab' | 'bitbucket' | 'azure_devops'

function normalizeScm(scm: string): ScmTypeId {
  const s = scm.toLowerCase().replace(/-/g, '_')
  if (s === 'gitlab') return 'gitlab'
  if (s === 'bitbucket') return 'bitbucket'
  if (s === 'azure_devops' || s === 'azuredevops') return 'azure_devops'
  return 'github'
}

const LABELS: Record<ScmTypeId, string> = {
  github: 'GitHub',
  gitlab: 'GitLab',
  bitbucket: 'Bitbucket',
  azure_devops: 'Azure DevOps',
}

/** Simple Icons CDN slug (see https://simpleicons.org/) */
function cdnSlug(id: ScmTypeId): string {
  if (id === 'azure_devops') return 'azuredevops'
  return id
}

/** Hex without # — brand colors */
const COLORS: Record<ScmTypeId, string> = {
  github: '181717',
  gitlab: 'FC6D26',
  bitbucket: '0052CC',
  azure_devops: '0078D4',
}

export function ScmLogo({
  scm,
  className = 'h-5 w-5',
}: {
  scm: string
  className?: string
}) {
  const id = normalizeScm(scm)
  const label = LABELS[id]
  const src = `https://cdn.simpleicons.org/${cdnSlug(id)}/${COLORS[id]}`

  return (
    <span className={`inline-flex items-center justify-center ${className}`} title={label} aria-label={label}>
      <img
        src={src}
        alt=""
        width={20}
        height={20}
        className={`h-full w-full object-contain ${id === 'github' ? 'dark:invert dark:opacity-90' : ''}`}
        loading="lazy"
      />
    </span>
  )
}
