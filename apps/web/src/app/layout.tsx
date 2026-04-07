import type { Metadata } from 'next'
import { JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from '@/lib/providers'

const mono = JetBrains_Mono({ subsets: ['latin'], weight: ['400', '500', '700'] })

export const metadata: Metadata = {
  title: 'Horion — Reliability Engineering Platform',
  description: 'AI-powered Reliability Engineering Platform',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){
              var old=localStorage.getItem('lumis_theme');
              if(old){localStorage.setItem('hz-theme',old);localStorage.removeItem('lumis_theme');}
              var t=localStorage.getItem('hz-theme');
              if(t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme: dark)').matches)){
                document.documentElement.classList.add('dark');
              }
            })()`.replace(/\s+/g,' '),
          }}
        />
      </head>
      <body className={mono.className}>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
