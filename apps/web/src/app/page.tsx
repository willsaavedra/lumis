import Link from 'next/link'
import Image from 'next/image'
import { ThemeToggle } from '@/components/ThemeToggle'

const OBS_TOOLS = [
  { id: 'opentelemetry', label: 'OpenTelemetry', color: '425CC7', darkColor: '7C9EF5' },
  { id: 'datadog', label: 'Datadog', color: '632CA6', darkColor: 'a472e8' },
  { id: 'grafana', label: 'Grafana', color: 'F46800', darkColor: 'F46800' },
  { id: 'prometheus', label: 'Prometheus', color: 'E6522C', darkColor: 'E6522C' },
] as const

function ToolLogo({
  id,
  label,
  color,
  size = 20,
}: {
  id: string
  label: string
  color: string
  size?: number
}) {
  return (
    <Image
      src={`https://cdn.simpleicons.org/${id}/${color}`}
      alt={label}
      width={size}
      height={size}
      className="object-contain"
      unoptimized
    />
  )
}

function IconGitHub({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
    </svg>
  )
}

function IconGitLab({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M23.955 13.587l-1.342-4.135-2.664-8.189a.455.455 0 00-.867 0L16.418 9.45H7.582L4.918 1.263a.455.455 0 00-.867 0L1.386 9.45.044 13.587a.924.924 0 00.331 1.023L12 23.054l11.625-8.443a.924.924 0 00.33-1.024z" />
    </svg>
  )
}

function IconBitbucket({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M.778 1.213a.768.768 0 00-.768.892l3.263 19.81c.084.5.515.873 1.022.873h15.41a.768.768 0 00.768-.646l3.263-20.037a.768.768 0 00-.768-.892zM14.52 15.53H9.522L8.17 8.466h7.652z" />
    </svg>
  )
}

function CodeBlock({ filename, children }: { filename: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl overflow-hidden text-xs"
      style={{ background: 'var(--hz-bg)', border: '1px solid var(--hz-rule)' }}
    >
      <div
        className="flex items-center gap-1.5 px-4 py-3 border-b"
        style={{ borderColor: 'var(--hz-rule)', background: 'var(--hz-bg2)' }}
      >
        <span className="w-2.5 h-2.5 rounded-full" style={{ background: 'var(--hz-rule2)' }} />
        <span className="w-2.5 h-2.5 rounded-full" style={{ background: 'var(--hz-rule2)' }} />
        <span className="w-2.5 h-2.5 rounded-full" style={{ background: 'var(--hz-rule2)' }} />
        <span className="ml-2 hz-sm">{filename}</span>
      </div>
      {children}
    </div>
  )
}

export default function LandingPage() {
  return (
    <div className="relative min-h-screen" style={{ background: 'var(--hz-bg)', color: 'var(--hz-ink)' }}>
      <div className="hz-grid-bg pointer-events-none fixed inset-0 z-0" style={{ opacity: 0.5 }} aria-hidden />
      <div className="relative z-10 min-h-screen">
      {/* Nav */}
      <nav className="px-10 py-4" style={{ borderBottom: '1px solid var(--hz-rule)' }}>
        <div className="flex items-center justify-between">
          <div>
            <span className="font-bold text-lg tracking-tight" style={{ letterSpacing: '-0.04em', color: 'var(--hz-ink)' }}>
              horion.pro<span className="hz-cursor" />
            </span>
            <p className="hz-micro mt-0.5" style={{ color: 'var(--hz-muted)' }}>Reliability Engineering Platform</p>
          </div>
          <div className="flex items-center gap-5 sm:gap-6">
            <Link href="/pricing" className="hz-body transition-opacity hover:opacity-80" style={{ fontSize: '13px', color: 'var(--hz-muted)' }}>
              pricing
            </Link>
            <Link href="/login" className="hz-body transition-opacity hover:opacity-80" style={{ fontSize: '13px', color: 'var(--hz-muted)' }}>
              log in
            </Link>
            <ThemeToggle />
            <Link href="/signup" className="hz-btn hz-btn-primary shrink-0">
              get started
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="px-10 pt-24 pb-20" style={{ borderBottom: '1px solid var(--hz-rule)' }}>
        <div className="grid grid-cols-2 gap-16 items-center">
          <div>
            <div
              className="inline-block hz-label rounded px-2 py-1 mb-6"
              style={{ border: '1px solid var(--hz-rule)', color: 'var(--hz-muted)' }}
            >
              AI-powered reliability engineering analysis
            </div>
            <h1 className="text-5xl font-bold leading-tight mb-6 tracking-tight" style={{ color: 'var(--hz-ink)' }}>
              Your code ships.<br />
              Your metrics don&apos;t lie.<br />
              <span style={{ color: 'var(--hz-muted)' }}>Horion finds the gap.</span>
            </h1>
            <p className="hz-body text-base mb-8 max-w-xl">
              Connect your repo. Horion analyzes metrics, logs, and traces instrumentation in your code,
              scores each pillar, and opens a PR with the actual fixes.
            </p>
            <div className="flex flex-wrap items-center gap-4">
              <Link href="/signup" className="hz-btn hz-btn-primary">
                start free — no card required
              </Link>
              <Link href="/pricing" className="hz-btn hz-btn-outline">
                see pricing
              </Link>
            </div>
          </div>
          <CodeBlock filename="horion — analysis complete">
            <pre className="p-6 leading-relaxed overflow-x-auto text-xs" style={{ color: 'var(--hz-ink2)' }}>{`$ horion analyze --repo acme/payments --type full

  Cloning repo...        done
  Walking 47 files...    done
  Running LLM analysis...

  Pillar       Score   Grade   Findings
  ─────────────────────────────────────
  Metrics        48      D       12
  Logs           72      C        4
  Traces         63      C        7
  ─────────────────────────────────────
  Global         61      C       23

  3 critical  ·  11 warning  ·  9 info

  Fix PR ready: github.com/acme/payments/pull/84`}</pre>
          </CodeBlock>
        </div>
      </section>

      {/* How it works */}
      <section className="px-10 py-20">
        <p className="hz-label mb-16">how it works</p>

        {/* Step 1 — text left, code right */}
        <div className="mb-24 grid grid-cols-2 gap-16 items-center">
          <div>
            <div className="hz-sm mb-2">01</div>
            <h2 className="text-2xl font-bold mb-4" style={{ color: 'var(--hz-ink)' }}>Connect your repository</h2>
            <p className="hz-body text-sm mb-8">
              Install the Horion app on your org. Every push and PR triggers an automatic analysis.
              Or run manually anytime from the dashboard.
            </p>
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2 hz-body text-sm" style={{ color: 'var(--hz-muted)' }}>
                <IconGitHub className="w-5 h-5 shrink-0" />
                <span>GitHub</span>
              </div>
              <div className="flex items-center gap-2 hz-body text-sm" style={{ color: 'var(--hz-muted)' }}>
                <IconGitLab className="w-5 h-5 shrink-0" />
                <span>GitLab</span>
              </div>
              <div className="flex items-center gap-2 hz-body text-sm" style={{ color: 'var(--hz-muted)' }}>
                <IconBitbucket className="w-5 h-5 shrink-0" />
                <span>Bitbucket</span>
              </div>
            </div>
          </div>
          <CodeBlock filename="horion.yml">
            <pre className="p-6 leading-relaxed overflow-x-auto text-xs" style={{ color: 'var(--hz-ink2)' }}>{`# .github/horion.yml
on:
  - push
  - pull_request

analysis:
  type: full
  pillars:
    - metrics
    - logs
    - traces

notify:
  fix_pr: true       # auto-open a fix PR
  comment_on_pr: true`}</pre>
          </CodeBlock>
        </div>

        {/* Step 2 — code left, text right */}
        <div className="mb-24 grid grid-cols-2 gap-16 items-center">
          <CodeBlock filename="analysis output">
            <pre className="p-6 leading-relaxed overflow-x-auto text-xs" style={{ color: 'var(--hz-ink2)' }}>{`{
  "score_global": 61,
  "score_metrics": 48,   // missing histograms
  "score_logs":    72,   // high noise on DEBUG
  "score_traces":  63,   // no span propagation
  "findings": [
    {
      "severity": "critical",
      "pillar": "metrics",
      "title": "No latency histogram on /checkout",
      "file_path": "src/handlers/checkout.py",
      "line_start": 34
    }
  ]
}`}</pre>
          </CodeBlock>
          <div>
            <div className="hz-sm mb-2">02</div>
            <h2 className="text-2xl font-bold mb-4" style={{ color: 'var(--hz-ink)' }}>Horion scores your instrumentation</h2>
            <p className="hz-body text-sm mb-8">
              The agent clones your repo, walks every file, and grades metrics coverage,
              log signal-to-noise ratio, and trace propagation — each on a 0–100 scale.
            </p>
            <div className="flex flex-wrap items-center gap-6">
              {OBS_TOOLS.map(({ id, label, color, darkColor }) => (
                <div
                  key={id}
                  className="flex items-center gap-2 hz-body text-sm"
                >
                  <span className="shrink-0 w-5 h-5 dark:hidden">
                    <ToolLogo id={id} label={label} color={color} size={20} />
                  </span>
                  <span className="shrink-0 w-5 h-5 hidden dark:inline">
                    <ToolLogo id={id} label={label} color={darkColor} size={20} />
                  </span>
                  <span>{label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Step 3 — text left, code right */}
        <div className="mb-24 grid grid-cols-2 gap-16 items-center">
          <div>
            <div className="hz-sm mb-2">03</div>
            <h2 className="text-2xl font-bold mb-4" style={{ color: 'var(--hz-ink)' }}>Review findings in-context</h2>
            <p className="hz-body text-sm">
              Each finding is pinned to the exact file and line. The suggested fix is shown as a
              complete code snippet — not a vague description.
            </p>
          </div>
          <CodeBlock filename="src/handlers/checkout.py  line 34">
            <div className="p-6 leading-relaxed font-mono text-xs">
              <div className="mb-1 hz-sm"># before</div>
              <div style={{ color: 'var(--hz-crit)' }}>-  logger.info(&quot;checkout started&quot;)</div>
              <div style={{ color: 'var(--hz-crit)' }}>-  result = process_payment(cart)</div>
              <div className="mb-4" style={{ color: 'var(--hz-crit)' }}>-  logger.info(&quot;checkout done&quot;)</div>
              <div className="mb-1 hz-sm"># after  (Horion suggestion)</div>
              <div style={{ color: 'var(--hz-ok)' }}>+  CHECKOUT_LATENCY = Histogram(</div>
              <div style={{ color: 'var(--hz-ok)' }}>+      &quot;checkout_latency_seconds&quot;,</div>
              <div style={{ color: 'var(--hz-ok)' }}>+      &quot;End-to-end checkout duration&quot;,</div>
              <div style={{ color: 'var(--hz-ok)' }}>+      buckets=[.05,.1,.25,.5,1,2.5,5]</div>
              <div style={{ color: 'var(--hz-ok)' }}>+  )</div>
              <div style={{ color: 'var(--hz-ok)' }}>+  with CHECKOUT_LATENCY.time():</div>
              <div style={{ color: 'var(--hz-ok)' }}>+      result = process_payment(cart)</div>
            </div>
          </CodeBlock>
        </div>

        {/* Step 4 — code left, text right */}
        <div className="grid grid-cols-2 gap-16 items-center">
          <CodeBlock filename="github pull request">
            <pre className="p-6 leading-relaxed overflow-x-auto text-xs" style={{ color: 'var(--hz-ink2)' }}>{`horion-bot opened a PR 3 minutes ago

[horion] fix observability — 4 findings

  branch: horion/fix-observability-2024-04-01

  | file                        | finding             |
  |-----------------------------|---------------------|
  | src/handlers/checkout.py    | latency histogram   |
  | src/workers/email.py        | span propagation    |
  | src/api/users.py            | DEBUG log noise     |
  | infra/otel-collector.yaml   | pipeline drop rule  |

  Score before: 61  ->  Score after (est.): 84`}</pre>
          </CodeBlock>
          <div>
            <div className="hz-sm mb-2">04</div>
            <h2 className="text-2xl font-bold mb-4" style={{ color: 'var(--hz-ink)' }}>Merge the fix PR</h2>
            <p className="hz-body text-sm">
              One click enqueues Claude to write the actual patches, push a branch,
              and open a PR. You review, merge, and ship better observability.
            </p>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section style={{ borderTop: '1px solid var(--hz-rule)' }}>
        <div className="px-10 py-20 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
          <div>
            <h2 className="text-2xl font-bold mb-1" style={{ color: 'var(--hz-ink)' }}>Ready to illuminate your stack?</h2>
            <p className="hz-body text-sm">50 free credits every month. No credit card required.</p>
          </div>
          <Link href="/signup" className="hz-btn hz-btn-primary whitespace-nowrap px-6 py-3">
            get started free
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: '1px solid var(--hz-rule)' }}>
        <div className="px-10 py-6 flex flex-wrap items-center justify-between gap-4 hz-sm">
          <span style={{ fontWeight: 700, letterSpacing: '-0.04em', color: 'var(--hz-ink)' }}>horion.pro</span>
          <div className="flex items-center gap-6">
            <Link href="/pricing" style={{ color: 'var(--hz-muted)' }} className="transition-opacity hover:opacity-80">
              pricing
            </Link>
            <Link href="/login" style={{ color: 'var(--hz-muted)' }} className="transition-opacity hover:opacity-80">
              log in
            </Link>
            <Link href="/signup" style={{ color: 'var(--hz-muted)' }} className="transition-opacity hover:opacity-80">
              sign up
            </Link>
          </div>
        </div>
      </footer>

      </div>
    </div>
  )
}
