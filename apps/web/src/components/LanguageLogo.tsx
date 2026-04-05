import { BadgeIcon } from '@/components/BadgeIcon'

type LanguageId =
  | 'python'
  | 'go'
  | 'typescript'
  | 'javascript'
  | 'java'
  | 'rust'
  | 'csharp'
  | 'ruby'
  | 'other'

function normalizeLanguage(language: string): LanguageId {
  const l = language.trim().toLowerCase()
  if (l === 'go' || l === 'golang') return 'go'
  if (l === 'typescript' || l === 'ts') return 'typescript'
  if (l === 'javascript' || l === 'js') return 'javascript'
  if (l === 'java') return 'java'
  if (l === 'python' || l === 'py') return 'python'
  if (l === 'rust' || l === 'rs') return 'rust'
  if (l === 'c#' || l === 'csharp' || l === 'c-sharp') return 'csharp'
  if (l === 'ruby' || l === 'rb') return 'ruby'
  return 'other'
}

const LABELS: Record<LanguageId, string> = {
  python: 'Python',
  go: 'Go',
  typescript: 'TypeScript',
  javascript: 'JavaScript',
  java: 'Java',
  rust: 'Rust',
  csharp: 'C#',
  ruby: 'Ruby',
  other: 'Other',
}

const COLORS: Record<Exclude<LanguageId, 'other'>, string> = {
  python: '3776AB',
  go: '00ADD8',
  typescript: '3178C6',
  javascript: 'F7DF1E',
  java: '007396',
  rust: '000000',
  csharp: '512BD4',
  ruby: 'CC342D',
}

function slug(id: Exclude<LanguageId, 'other'>): string {
  if (id === 'csharp') return 'csharp'
  return id
}

export function LanguageLogo({ language }: { language: string }) {
  const id = normalizeLanguage(language)
  if (id === 'other') return null

  const src = `https://cdn.simpleicons.org/${slug(id)}/${COLORS[id]}`
  const invertOnDark = id === 'rust'

  return <BadgeIcon title={LABELS[id]} src={src} invertOnDark={invertOnDark} />
}

