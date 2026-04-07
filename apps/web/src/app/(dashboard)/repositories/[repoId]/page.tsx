import RepoDetailClient from './RepoDetailClient'

// Required for Next.js static export (output: 'export').
// Route param resolved via useParams() inside the client component.
export async function generateStaticParams() {
  // Returns a single placeholder so Next.js generates the HTML shell.
  // CloudFront serves this shell for any /repositories/* path via a custom error response.
  return [{ repoId: '_' }]
}

export default function Page() {
  return <RepoDetailClient />
}
