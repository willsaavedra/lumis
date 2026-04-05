/**
 * Small icon chip used in repo metadata rows.
 */
export function BadgeIcon({
  title,
  src,
  className = '',
  imageClassName = 'h-4 w-4',
  invertOnDark = false,
}: {
  title: string
  src: string
  className?: string
  imageClassName?: string
  invertOnDark?: boolean
}) {
  return (
    <span
      className={`inline-flex items-center justify-center ${className}`}
      title={title}
      aria-label={title}
    >
      <img
        src={src}
        alt=""
        width={16}
        height={16}
        className={`object-contain ${imageClassName} ${invertOnDark ? 'dark:invert dark:opacity-90' : ''}`}
        loading="lazy"
      />
    </span>
  )
}

