import AnalysisDetailClient from './AnalysisDetailClient'

// Required for Next.js static export (output: 'export').
// All data is fetched client-side; CloudFront serves the HTML shell for any /analyses/* path.
export async function generateStaticParams() {
  // Returns a single placeholder so Next.js generates the HTML shell.
  // CloudFront serves this shell for any /analyses/* path via a custom error response.
  return [{ id: '_' }]
}

export default function Page({ params }: { params: { id: string } }) {
  return <AnalysisDetailClient params={params} />
}
