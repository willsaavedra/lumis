import RepoDetailClient from './RepoDetailClient'

// Required for Next.js static export (output: 'export').
// Route param resolved via useParams() inside the client component.
export async function generateStaticParams() {
  return []
}

export default function Page() {
  return <RepoDetailClient />
}
