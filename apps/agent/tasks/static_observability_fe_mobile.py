"""
Curated static RAG chunks: observability for browsers, SPAs, and mobile clients.

Complements backend/IaC-heavy _STATIC_KNOWLEDGE in ingest_global_docs.
"""

# (source_id, pillar, markdown_content)
STATIC_OBSERVABILITY_FE_MOBILE: list[tuple[str, str, str]] = [
    (
        "observability-browser-rum-otel",
        "traces",
        """# Browser and SPA Observability

## Real User Monitoring (RUM) vs backend APM
- **RUM** measures what end users experience (latency, errors, Core Web Vitals) from the browser.
- **Backend APM** measures server-side request handling. Both are required; neither replaces the other.
- Correlate RUM sessions with backend traces using shared **trace_id** propagated from browser to API.

## OpenTelemetry in the browser
- Use `@opentelemetry/sdk-trace-web` with a `WebTracerProvider` and appropriate exporter (OTLP HTTP to collector).
- Instrument **fetch/XHR** and **document load** via instrumentation packages; add manual spans for route transitions in SPAs.
- Propagate context on async boundaries: promises, `setTimeout`, and framework schedulers may drop context unless using zone.js or explicit context helpers.
- Never ship PII in span attributes; use hashed user identifiers only if required.

## Web Vitals (quality signals)
- **LCP** (Largest Contentful Paint): loading performance — optimize images, fonts, critical CSS.
- **INP** (Interaction to Next Paint): responsiveness — reduce long tasks, split JS bundles.
- **CLS** (Cumulative Layout Shift): visual stability — size images, avoid inserting content above existing content.
- Report vitals as OTel metrics or vendor RUM; alert on regression vs baseline per route.

## Error tracking in SPAs
- Capture unhandled errors and promise rejections; attach **release version** and **build id** for source map resolution.
- Use error boundaries (React) or global handlers (Vue) and record exceptions on the active span.
- Map minified stack traces via source maps stored privately (not public buckets without auth).

## Framework patterns
- **React**: wrap router with tracing; trace Suspense boundaries sparingly to avoid span explosion.
- **Next.js**: distinguish server vs client components; server traces belong to Node exporter, browser traces to web SDK.
- **Mobile web**: test on low-end devices; long tasks break INP — profile before shipping.

## Privacy and sampling
- Sample client traces aggressively (e.g. 1–5%) unless debugging; always strip query strings from URLs in span names.
""",
    ),
    (
        "observability-mobile-native",
        "traces",
        """# Mobile app observability (iOS and Android)

## Goals
- Detect crashes, ANRs (Android), and hangs (iOS); tie them to **releases** and **device/OS** dimensions.
- Measure cold start, screen transitions, and network calls without excessive battery use.

## OpenTelemetry mobile
- Use official OTel mobile exporters where available; otherwise bridge vendor SDKs (Firebase Performance, etc.) into OTel pipelines.
- Propagate trace context from mobile clients to backends on every API call (W3C traceparent headers).
- Create spans for **screen views** and **user actions**; avoid high-cardinality span names (use attributes instead).

## Crashes vs handled errors
- **Crashes**: capture native stack traces; symbolicate with dSYM / ProGuard mapping files stored per build.
- **Handled errors**: log to logging backend with severity; optionally record as span events, not always as new traces.

## Metrics
- Track session duration, screen time, API error rate by endpoint, push notification delivery.
- Use low-cardinality labels: app_version, os, country (coarse), not user_id as a metric label.

## Session correlation
- Generate a **session_id** early in app launch; pass to RUM and backend as baggage or custom header for support workflows.
""",
    ),
]

# URLs for weekly fetch: (url, language_hint, pillar_hint)
FE_MOBILE_DOC_URLS: list[tuple[str, str | None, str]] = [
    (
        "https://opentelemetry.io/docs/languages/js/getting-started/browser/",
        "javascript",
        "traces",
    ),
    (
        "https://opentelemetry.io/docs/languages/js/instrumentation/",
        "javascript",
        "traces",
    ),
    ("https://web.dev/vitals/", None, "metrics"),
]
