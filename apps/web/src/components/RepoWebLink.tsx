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
      className={`hover:underline text-inherit hover:text-blue-600 dark:hover:text-blue-400 ${className}`}
      onClick={(e) => e.stopPropagation()}
    >
      {name}
    </a>
  )
}
