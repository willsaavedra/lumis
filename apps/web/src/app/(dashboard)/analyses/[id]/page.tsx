import AnalysisDetailClient from './AnalysisDetailClient'

// Required for Next.js static export (output: 'export').
// All data is fetched client-side; CloudFront serves the HTML shell for any /analyses/* path.
export async function generateStaticParams() {
  return []
}

export default function Page({ params }: { params: { id: string } }) {
  return <AnalysisDetailClient params={params} />
}
