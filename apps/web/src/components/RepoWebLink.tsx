'use client'

/**
 * Repository name as an external link to the Git host (GitHub, GitLab, etc.).
 */
export function RepoWebLink({
  name,
  href,
  className = '',
}: {
  name: string
  href: string
  className?: string
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={`Open ${name} on Git host`}
      className={`hover:underline ${className}`}
      style={{ color: 'inherit' }}
      onMouseEnter={(e) => {
        e.currentTarget.style.color = 'var(--hz-info)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.color = 'inherit'
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {name}
    </a>
  )
}
