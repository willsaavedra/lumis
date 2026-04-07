'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reposApi, analysesApi, Repository, connectionsApi, type ScmConnection } from '@/lib/api'
import { RepoWebLink } from '@/components/RepoWebLink'
import { ScmLogo } from '@/components/ScmLogo'
import { formatDate } from '@/lib/utils'
import { useState, useRef, useEffect, useMemo } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ExternalLink, Search } from 'lucide-react'
import { RepoContentsPicker, type ScopeItem } from '@/components/RepoContentsPicker'
import { toast } from '@/components/Toast'

const REPO_TYPES = [
  { value: 'app', label: 'Application', description: 'Web service, API, worker' },
  { value: 'iac', label: 'Infrastructure as Code', description: 'Terraform, Pulumi, CDK' },
  { value: 'library', label: 'Library / SDK', description: 'Shared library or internal package' },
  { value: 'monorepo', label: 'Monorepo', description: 'Multiple services in one repo' },
]

const APP_SUBTYPES = [
  { value: 'web_service', label: 'Web Service' },
  { value: 'api', label: 'API' },
  { value: 'worker', label: 'Worker / Consumer' },
  { value: 'websocket', label: 'WebSocket' },
  { value: 'cli', label: 'CLI Tool' },
  { value: 'other', label: 'Other' },
]

const IAC_PROVIDERS = [
  { value: 'aws', label: 'AWS' },
  { value: 'azure', label: 'Azure' },
  { value: 'gcp', label: 'Google Cloud' },
  { value: 'multi', label: 'Multi-cloud' },
  { value: 'other', label: 'Other' },
]

const LANGUAGES = ['Python', 'Go', 'TypeScript', 'JavaScript', 'Java', 'Rust', 'C#', 'Ruby', 'Other']

const OBS_BACKENDS = [
  { value: 'datadog', label: 'Datadog' },
  { value: 'grafana', label: 'Grafana' },
  { value: 'prometheus', label: 'Prometheus' },
  { value: 'dynatrace', label: 'Dynatrace' },
  { value: 'splunk', label: 'Splunk' },
]

const INSTRUMENTATIONS = [
  { value: 'otel', label: 'OpenTelemetry', description: 'OTEL SDK — vendor-neutral' },
  { value: 'datadog', label: 'Datadog tracer', description: 'dd-trace / ddtrace' },
  { value: 'mixed', label: 'Mixed', description: 'Both OTEL and dd-trace' },
  { value: 'none', label: 'None', description: 'No instrumentation yet' },
  { value: 'other', label: 'Other', description: 'Another library' },
]

interface ContextForm {
  repo_type: string
  app_subtype: string
  iac_provider: string
  languages: string[]
  observability_backend: string
  instrumentation: string
  service_name: string
  environment: string
  obs_kv: { key: string; value: string }[]
  context_summary: string
}

const EMPTY_CONTEXT: ContextForm = {
  repo_type: '',
  app_subtype: '',
  iac_provider: '',
  languages: [],
  observability_backend: '',
  instrumentation: '',
  service_name: '',
  environment: '',
  obs_kv: [],
  context_summary: '',
}

function buildObsMetadata(form: ContextForm): Record<string, unknown> | undefined {
  const meta: Record<string, unknown> = {}
  if (form.service_name.trim()) meta.service_name = form.service_name.trim()
  if (form.environment.trim()) meta.environment = form.environment.trim()
  if (form.obs_kv.length > 0) {
    const pairs = form.obs_kv.filter((p) => p.key.trim())
    if (pairs.length > 0) {
      const kvMap = Object.fromEntries(pairs.map((p) => [p.key.trim(), p.value.trim()]))
      if (form.observability_backend === 'datadog') meta.tags = kvMap
      else if (form.observability_backend === 'prometheus' || form.observability_backend === 'grafana') meta.labels = kvMap
    }
  }
  return Object.keys(meta).length > 0 ? meta : undefined
}

function repoTypeShortLabel(repo: Repository): string | null {
  if (!repo.repo_type) return null
  if (repo.repo_type === 'app' && repo.app_subtype) {
    return `App · ${repo.app_subtype.replace(/_/g, ' ')}`
  }
  if (repo.repo_type === 'iac' && repo.iac_provider) {
    return `IaC · ${repo.iac_provider.toUpperCase()}`
  }
  const t = REPO_TYPES.find((x) => x.value === repo.repo_type)
  return t?.label ?? repo.repo_type
}

/** Full-width context block: no hard ellipsis; long text can expand. */
function RepoContextSummary({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  const isLong = text.length > 260 || text.split(/\n/).length > 5

  return (
    <div
      style={{
        marginTop: '14px',
        paddingTop: '14px',
        borderTop: '1px solid var(--hz-rule)',
      }}
    >
      <div className="hz-label" style={{ marginBottom: '6px', color: 'var(--hz-muted)' }}>
        Context
      </div>
      <p
        className={!expanded && isLong ? 'line-clamp-4' : ''}
        style={{
          margin: 0,
          fontSize: '12px',
          lineHeight: 1.65,
          color: 'var(--hz-ink2)',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        {text}
      </p>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="hz-sm mt-2"
          style={{
            color: 'var(--hz-ink)',
            background: 'transparent',
            border: 'none',
            padding: 0,
            cursor: 'pointer',
            textDecoration: 'underline',
            textUnderlineOffset: '3px',
          }}
        >
          {expanded ? 'Show less' : 'Show full context'}
        </button>
      )}
    </div>
  )
}

function repoToContextForm(repo: Repository): ContextForm {
  const meta = (repo.obs_metadata ?? {}) as Record<string, unknown>
  const kvSource = (meta.tags ?? meta.labels ?? {}) as Record<string, string>
  return {
    repo_type: repo.repo_type ?? '',
    app_subtype: repo.app_subtype ?? '',
    iac_provider: repo.iac_provider ?? '',
    languages: repo.language ?? [],
    observability_backend: repo.observability_backend ?? '',
    instrumentation: repo.instrumentation ?? '',
    service_name: (meta.service_name as string) ?? '',
    environment: (meta.environment as string) ?? '',
    obs_kv: Object.entries(kvSource).map(([key, value]) => ({ key, value })),
    context_summary: repo.context_summary ?? '',
  }
}

function _friendlyAnalysisError(detail: string): string {
  if (detail.includes('Credit limit') || detail.includes('credits remaining')) {
    return `You've used all available credits this period. Upgrade your plan in Billing to continue.`
  }
  if (detail.includes('Subscription inactive') || detail.includes('payment method')) {
    return 'Your subscription is inactive. Update your payment method in Billing.'
  }
  if (detail.includes('not found') || detail.includes('not active')) {
    return 'Repository not found or inactive.'
  }
  return detail
}

type AddStep = 'select' | 'context'

interface PendingRepo {
  scm_repo_id: string
  full_name: string
  default_branch: string
  clone_url?: string
  html_url?: string
  /** github | gitlab | bitbucket — from /repositories/available */
  scm_type?: string
}

type ScmChoiceId = 'github' | 'gitlab' | 'bitbucket'

function connectedScmTypesList(conns: ScmConnection[] | undefined): ScmChoiceId[] {
  if (!conns?.length) return []
  const seen = new Set<ScmChoiceId>()
  for (const c of conns) {
    if (c.scm_type === 'github' && c.installation_id) seen.add('github')
    else if (c.scm_type === 'gitlab') seen.add('gitlab')
    else if (c.scm_type === 'bitbucket') seen.add('bitbucket')
  }
  return Array.from(seen)
}

const SCM_CHOICE_LABEL: Record<ScmChoiceId, string> = {
  github: 'GitHub',
  gitlab: 'GitLab',
  bitbucket: 'Bitbucket',
}

export default function RepositoriesPage() {
  const router = useRouter()
  const qc = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)
  const [step, setStep] = useState<AddStep>('select')
  const [pending, setPending] = useState<PendingRepo | null>(null)
  const [context, setContext] = useState<ContextForm>(EMPTY_CONTEXT)
  const [analyzingId, setAnalyzingId] = useState<string | null>(null)
  const [analyzeModal, setAnalyzeModal] = useState<{ repo: Repository } | null>(null)
  const [selectAll, setSelectAll] = useState(true)
  const [selectedProvider, setSelectedProvider] = useState<'anthropic' | 'cerebra_ai'>('anthropic')
  const [analyzeBranch, setAnalyzeBranch] = useState('')
  const [quickScope, setQuickScope] = useState<ScopeItem[]>([])
  const [estimate, setEstimate] = useState<{ file_count: number; estimated_credits: number; analysis_type: string } | null>(null)
  const [estimating, setEstimating] = useState(false)
  const [editingContextId, setEditingContextId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<ContextForm>(EMPTY_CONTEXT)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [contextDiscoveryRepoId, setContextDiscoveryRepoId] = useState<string | null>(null)
  const [contextDiscoveryJobId, setContextDiscoveryJobId] = useState<string | null>(null)
  const [addRepoScmChoice, setAddRepoScmChoice] = useState<ScmChoiceId | null>(null)
  const [addRepoSearch, setAddRepoSearch] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Debounced credit estimate when the analyze modal is open
  useEffect(() => {
    if (!analyzeModal) return
    const repoId = analyzeModal.repo.id
    const paths = selectAll ? null : quickScope.map((s) => s.path)
    const ref = analyzeBranch.trim() || analyzeModal.repo.default_branch
    const timer = setTimeout(async () => {
      setEstimating(true)
      try {
        const result = await analysesApi.estimate(repoId, paths, selectAll, ref)
        setEstimate(result)
      } catch {
        setEstimate(null)
      } finally {
        setEstimating(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [analyzeModal, selectAll, quickScope, analyzeBranch])

  // Poll context discovery job until complete
  useEffect(() => {
    if (!contextDiscoveryJobId) return
    pollRef.current = setInterval(async () => {
      try {
        const job = await analysesApi.get(contextDiscoveryJobId)
        if (job.status === 'completed') {
          clearInterval(pollRef.current!)
          setContextDiscoveryJobId(null)
          setContextDiscoveryRepoId(null)
          qc.invalidateQueries({ queryKey: ['repositories'] })
          toast('Context analysis complete — repository context is ready', 'success')
        } else if (job.status === 'failed') {
          clearInterval(pollRef.current!)
          setContextDiscoveryJobId(null)
          setContextDiscoveryRepoId(null)
          toast('Context analysis failed', 'error')
        }
      } catch {
        clearInterval(pollRef.current!)
        setContextDiscoveryJobId(null)
        setContextDiscoveryRepoId(null)
      }
    }, 3000)
    return () => clearInterval(pollRef.current!)
  }, [contextDiscoveryJobId])

  const { data: repos } = useQuery({
    queryKey: ['repositories'],
    queryFn: reposApi.list,
  })

  const { data: scmConnections, isLoading: scmConnectionsLoading } = useQuery({
    queryKey: ['scm-connections'],
    queryFn: connectionsApi.list,
    enabled: showAdd && step === 'select',
  })

  const connectedScmTypes = useMemo(() => connectedScmTypesList(scmConnections), [scmConnections])

  const effectiveAddScm = useMemo((): ScmChoiceId | null => {
    if (connectedScmTypes.length === 0) return null
    if (connectedScmTypes.length === 1) return connectedScmTypes[0]
    return addRepoScmChoice
  }, [connectedScmTypes, addRepoScmChoice])

  const { data: available, isLoading: availableLoading } = useQuery({
    queryKey: ['available-repos'],
    queryFn: reposApi.available,
    enabled:
      showAdd &&
      step === 'select' &&
      scmConnections !== undefined &&
      connectedScmTypes.length > 0 &&
      effectiveAddScm !== null,
  })

  const reposForSelectedScm = useMemo(() => {
    if (!available?.length || !effectiveAddScm) return []
    return available.filter((r: PendingRepo) => (r.scm_type || 'github') === effectiveAddScm)
  }, [available, effectiveAddScm])

  const filteredAvailableRepos = useMemo(() => {
    const q = addRepoSearch.trim().toLowerCase()
    if (!q) return reposForSelectedScm
    return reposForSelectedScm.filter((r: PendingRepo) => r.full_name.toLowerCase().includes(q))
  }, [reposForSelectedScm, addRepoSearch])

  const showAddScmPicker = connectedScmTypes.length > 1 && addRepoScmChoice === null

  const { data: repoRefs } = useQuery({
    queryKey: ['repo-refs', analyzeModal?.repo.id],
    queryFn: () => reposApi.listRefs(analyzeModal!.repo.id),
    enabled: !!analyzeModal,
    staleTime: 60_000,
  })

  const activateMutation = useMutation({
    mutationFn: (data: Parameters<typeof reposApi.create>[0]) => reposApi.create(data),
    onSuccess: (repo) => {
      qc.invalidateQueries({ queryKey: ['repositories'] })
      setShowAdd(false)
      setStep('select')
      setPending(null)
      setContext(EMPTY_CONTEXT)
      setAddRepoScmChoice(null)
      setAddRepoSearch('')
      toast(`${repo.full_name} added`, 'success')
      // Trigger context discovery and track progress
      analysesApi.trigger(repo.id, repo.default_branch, 'context')
        .then((job) => {
          setContextDiscoveryRepoId(repo.id)
          setContextDiscoveryJobId(job.id)
          toast('Analyzing repository context in the background...', 'info')
          router.push(`/analyses/${job.id}`)
        })
        .catch(() => null)
    },
  })

  const deactivateMutation = useMutation({
    mutationFn: (id: string) => reposApi.deactivate(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['repositories'] })
      setConfirmDeleteId(null)
      toast('Repository deactivated', 'success')
    },
    onError: () => toast('Failed to deactivate repository', 'error'),
  })

  const saveContextMutation = useMutation({
    mutationFn: ({ id, draft }: { id: string; draft: ContextForm }) =>
      reposApi.updateContext(id, {
        repo_type: draft.repo_type || undefined,
        app_subtype: draft.app_subtype || undefined,
        iac_provider: draft.iac_provider || undefined,
        language: draft.languages.length > 0 ? draft.languages : undefined,
        observability_backend: draft.observability_backend || undefined,
        instrumentation: draft.instrumentation || undefined,
        obs_metadata: buildObsMetadata(draft),
        context_summary: draft.context_summary || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['repositories'] })
      setEditingContextId(null)
      toast('Context updated', 'success')
    },
  })

  const triggerMutation = useMutation({
    mutationFn: async (payload: {
      repoId: string
      ref: string
      changedFiles?: string[] | null
      llmProvider?: 'anthropic' | 'cerebra_ai'
    }) => {
      setAnalyzingId(payload.repoId)
      return analysesApi.trigger(payload.repoId, payload.ref, undefined, payload.changedFiles ?? null, payload.llmProvider)
    },
    onSuccess: (data) => {
      toast('Analysis started — results will appear in Analyses', 'success')
      setAnalyzingId(null)
      setAnalyzeModal(null)
      setQuickScope([])
      setEstimate(null)
      router.push(`/analyses/${data.id}`)
    },
    onError: (err: any) => {
      const raw = err?.response?.data?.detail
      const detail =
        Array.isArray(raw) && raw[0]?.msg
          ? raw.map((x: { msg?: string }) => x.msg).filter(Boolean).join(' ')
          : typeof raw === 'string'
            ? raw
            : raw?.msg ?? raw
      const msg = detail
        ? _friendlyAnalysisError(String(detail))
        : 'Could not start analysis. Please try again.'
      toast(msg, 'error')
      setAnalyzingId(null)
    },
  })

  function openAnalyzeModal(repo: Repository) {
    setAnalyzeModal({ repo })
    setSelectAll(true)
    setSelectedProvider('anthropic')
    setAnalyzeBranch(repo.default_branch)
    setQuickScope([])
    setEstimate(null)
  }

  function submitAnalyze() {
    if (!analyzeModal) return
    if (!selectAll && quickScope.length === 0) return
    triggerMutation.mutate({
      repoId: analyzeModal.repo.id,
      ref: analyzeBranch.trim() || analyzeModal.repo.default_branch,
      changedFiles: selectAll ? null : quickScope.map((s) => s.path),
      llmProvider: selectedProvider,
    })
  }

  function openAdd() {
    setShowAdd(true)
    setStep('select')
    setPending(null)
    setContext(EMPTY_CONTEXT)
    setAddRepoScmChoice(null)
    setAddRepoSearch('')
  }

  function closeAdd() {
    setShowAdd(false)
    setStep('select')
    setPending(null)
    setContext(EMPTY_CONTEXT)
    setAddRepoScmChoice(null)
    setAddRepoSearch('')
  }

  function handleSelectRepo(r: PendingRepo) {
    setPending(r)
    setStep('context')
  }

  function handleFinish() {
    if (!pending) return
    activateMutation.mutate({
      scm_repo_id: pending.scm_repo_id,
      full_name: pending.full_name,
      default_branch: pending.default_branch,
      clone_url: pending.clone_url,
      scm_type: pending.scm_type || 'github',
      repo_type: context.repo_type || undefined,
      app_subtype: context.app_subtype || undefined,
      iac_provider: context.iac_provider || undefined,
      language: context.languages.length > 0 ? context.languages : undefined,
      observability_backend: context.observability_backend || undefined,
      instrumentation: context.instrumentation || undefined,
      obs_metadata: buildObsMetadata(context),
    })
  }

  const repoCount = repos?.length ?? 0
  const withSummary = repos?.filter((r) => (r.context_summary ?? '').trim().length > 0).length ?? 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%', background: 'var(--hz-bg)' }}>
      {/* Topbar */}
      <div
        style={{
          padding: '18px 24px 16px',
          borderBottom: '1px solid var(--hz-rule)',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: '12px',
        }}
      >
        <div>
          <h1 className="hz-h2" style={{ margin: 0, color: 'var(--hz-ink)' }}>Repositories</h1>
          <p className="hz-body" style={{ marginTop: '6px', marginBottom: 0, fontSize: '12px', color: 'var(--hz-muted)' }}>
            Connect repos and manage context for analyses
          </p>
        </div>
        <button type="button" onClick={openAdd} className="hz-btn hz-btn-primary">
          + Add repository
        </button>
      </div>

      {/* Mini stats */}
      <div
        className="grid grid-cols-1 sm:grid-cols-3 gap-px"
        style={{ borderBottom: '1px solid var(--hz-rule)', background: 'var(--hz-rule)' }}
      >
        {[
          { label: 'Connected repos', value: repoCount, sub: 'active in workspace', accent: 'var(--hz-ink)' },
          { label: 'With context summary', value: withSummary, sub: 'of ' + repoCount, accent: 'var(--hz-info)' },
          {
            label: 'SCM connections',
            value: connectedScmTypes.length || '—',
            sub: 'Git host(s) linked',
            accent: 'var(--hz-ok)',
          },
        ].map((s, i) => (
          <div
            key={i}
            style={{
              padding: '12px 20px',
              position: 'relative',
              overflow: 'hidden',
              background: 'var(--hz-bg)',
            }}
          >
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: s.accent }} />
            <div className="hz-grid-bg" style={{ position: 'absolute', inset: 0, opacity: 0.45, pointerEvents: 'none' }} />
            <div className="hz-label" style={{ marginBottom: '4px', position: 'relative', color: 'var(--hz-muted)' }}>
              {s.label}
            </div>
            <div
              style={{
                fontSize: '20px',
                fontWeight: 700,
                letterSpacing: '-0.04em',
                color: 'var(--hz-ink)',
                lineHeight: 1,
                position: 'relative',
              }}
            >
              {s.value}
            </div>
            <div className="hz-sm" style={{ marginTop: '3px', position: 'relative' }}>
              {s.sub}
            </div>
          </div>
        ))}
      </div>

      <div style={{ flex: 1, padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Repo list */}
      <div
        style={{
          border: '1px solid var(--hz-rule)',
          borderRadius: 'var(--hz-lg)',
          overflow: 'hidden',
          background: 'var(--hz-bg)',
        }}
      >
        {repos?.length === 0 && (
          <div className="hz-body" style={{ padding: '40px', textAlign: 'center', color: 'var(--hz-muted)' }}>
            No repositories yet. Connect a Git host in Settings → Connections, then add a repository.
          </div>
        )}
        {repos?.map((repo, ri) => (
          <div
            key={repo.id}
            style={{
              borderTop: ri > 0 ? '1px solid var(--hz-rule)' : 'none',
              padding: '18px 20px',
            }}
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-start gap-3 min-w-0 flex-1">
                <ScmLogo scm={repo.scm_type} className="h-7 w-7 shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <Link
                      href={`/repositories/${repo.id}`}
                      className="truncate hz-body hover:underline"
                      style={{ color: 'var(--hz-ink)', fontWeight: 600, fontSize: '14px' }}
                    >
                      {repo.full_name}
                    </Link>
                    <a
                      href={repo.web_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Open on Git host"
                      style={{ color: 'var(--hz-muted)' }}
                      className="shrink-0 hover:opacity-80 inline-flex"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                    </a>
                    {contextDiscoveryRepoId === repo.id && (
                      <span className="flex items-center gap-1 hz-sm font-normal" style={{ color: 'var(--hz-muted)' }}>
                        <span
                          className="inline-block w-3 h-3 rounded-full animate-spin shrink-0"
                          style={{ border: '2px solid var(--hz-rule2)', borderTopColor: 'transparent' }}
                        />
                        analyzing context…
                      </span>
                    )}
                  </div>
                  <p className="hz-sm m-0" style={{ color: 'var(--hz-muted)', lineHeight: 1.55 }}>
                    {repo.default_branch}
                    <span aria-hidden> · </span>
                    added {formatDate(repo.created_at)}
                    {repo.last_analysis_at && (
                      <>
                        <span aria-hidden> · </span>
                        last analysis {formatDate(repo.last_analysis_at)}
                      </>
                    )}
                    {(() => {
                      const bits: string[] = []
                      const rt = repoTypeShortLabel(repo)
                      if (rt) bits.push(rt)
                      if (repo.language && repo.language.length > 0) bits.push(repo.language.join(', '))
                      if (repo.observability_backend) {
                        const ob = OBS_BACKENDS.find((b) => b.value === repo.observability_backend)
                        bits.push(ob?.label ?? repo.observability_backend)
                      }
                      if (bits.length === 0) return null
                      return (
                        <>
                          <span aria-hidden> · </span>
                          {bits.join(' · ')}
                        </>
                      )
                    })()}
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 shrink-0 sm:pt-0.5 sm:justify-end">
                <button
                  type="button"
                  onClick={() => {
                    if (editingContextId === repo.id) {
                      setEditingContextId(null)
                    } else {
                      setEditingContextId(repo.id)
                      setEditDraft(repoToContextForm(repo))
                      setConfirmDeleteId(null)
                    }
                  }}
                  className="hz-btn hz-btn-outline"
                  style={{ fontSize: '11px', padding: '6px 12px' }}
                >
                  Edit context
                </button>
                <button
                  type="button"
                  onClick={() => openAnalyzeModal(repo)}
                  disabled={analyzingId === repo.id}
                  className="hz-btn hz-btn-primary"
                  style={{ fontSize: '11px', padding: '6px 12px' }}
                >
                  {analyzingId === repo.id ? (
                    <span className="inline-flex items-center gap-1.5">
                      <span
                        className="inline-block w-3 h-3 rounded-full animate-spin shrink-0"
                        style={{ border: '2px solid var(--hz-bg)', borderTopColor: 'transparent' }}
                      />
                      Analyzing…
                    </span>
                  ) : (
                    'Analyze now'
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => { setConfirmDeleteId(repo.id); setEditingContextId(null) }}
                  className="hz-btn hz-btn-ghost"
                  style={{ fontSize: '11px', padding: '6px 10px', color: 'var(--hz-muted)' }}
                  title="Remove repository"
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Context summary — full text or expand; hz tokens only */}
            {repo.context_summary && editingContextId !== repo.id && (
              <RepoContextSummary text={repo.context_summary} />
            )}

            {/* Full context edit panel */}
            {editingContextId === repo.id && (
              <div
                className="mt-4 pt-4 space-y-4 rounded-lg p-4"
                style={{
                  border: '1px solid var(--hz-rule)',
                  background: 'var(--hz-bg2)',
                }}
              >
                {/* Repo type */}
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Repository type</label>
                  <div className="grid grid-cols-4 gap-2">
                    {REPO_TYPES.map((t) => (
                      <button
                        key={t.value}
                        type="button"
                        onClick={() => setEditDraft((d) => ({ ...d, repo_type: d.repo_type === t.value ? '' : t.value, app_subtype: '', iac_provider: '' }))}
                        className={`text-left p-2 rounded-lg border text-xs transition-colors ${
                          editDraft.repo_type === t.value
                            ? 'border-gray-900 dark:border-gray-100 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                            : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500'
                        }`}
                      >
                        <div className="font-medium">{t.label}</div>
                        <div className="text-gray-400 dark:text-gray-500 text-[10px] mt-0.5">{t.description}</div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* App subtype */}
                {editDraft.repo_type === 'app' && (
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Application type</label>
                    <div className="flex flex-wrap gap-2">
                      {APP_SUBTYPES.map((s) => (
                        <button
                          key={s.value}
                          type="button"
                          onClick={() => setEditDraft((d) => ({ ...d, app_subtype: d.app_subtype === s.value ? '' : s.value }))}
                          className={`px-3 py-1 rounded text-xs border transition-colors ${
                            editDraft.app_subtype === s.value
                              ? 'border-gray-900 dark:border-gray-100 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium'
                              : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400'
                          }`}
                        >{s.label}</button>
                      ))}
                    </div>
                  </div>
                )}

                {/* IaC provider */}
                {editDraft.repo_type === 'iac' && (
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Cloud provider</label>
                    <div className="flex flex-wrap gap-2">
                      {IAC_PROVIDERS.map((p) => (
                        <button
                          key={p.value}
                          type="button"
                          onClick={() => setEditDraft((d) => ({ ...d, iac_provider: d.iac_provider === p.value ? '' : p.value }))}
                          className={`px-3 py-1 rounded text-xs border transition-colors ${
                            editDraft.iac_provider === p.value
                              ? 'border-gray-900 dark:border-gray-100 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium'
                              : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400'
                          }`}
                        >{p.label}</button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Language */}
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Language(s)</label>
                  <div className="flex flex-wrap gap-2">
                    {LANGUAGES.map((lang) => (
                      <button
                        key={lang}
                        type="button"
                        onClick={() => setEditDraft((d) => ({
                          ...d,
                          languages: d.languages.includes(lang) ? d.languages.filter((l) => l !== lang) : [...d.languages, lang],
                        }))}
                        className={`px-3 py-1 rounded text-xs border transition-colors ${
                          editDraft.languages.includes(lang)
                            ? 'border-gray-900 dark:border-gray-100 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium'
                            : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400'
                        }`}
                      >{lang}</button>
                    ))}
                  </div>
                </div>

                {/* Observability backend */}
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Observability backend</label>
                  <div className="flex flex-wrap gap-2">
                    {OBS_BACKENDS.map((b) => (
                      <button
                        key={b.value}
                        type="button"
                        onClick={() => setEditDraft((d) => ({ ...d, observability_backend: d.observability_backend === b.value ? '' : b.value, obs_kv: [] }))}
                        className={`px-3 py-1 rounded text-xs border transition-colors ${
                          editDraft.observability_backend === b.value
                            ? 'border-gray-900 dark:border-gray-100 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium'
                            : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400'
                        }`}
                      >{b.label}</button>
                    ))}
                  </div>
                </div>

                {/* Instrumentation */}
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Instrumentation library</label>
                  <div className="grid grid-cols-3 gap-2">
                    {INSTRUMENTATIONS.map((inst) => (
                      <button
                        key={inst.value}
                        type="button"
                        onClick={() => setEditDraft((d) => ({ ...d, instrumentation: d.instrumentation === inst.value ? '' : inst.value }))}
                        className={`text-left p-2 rounded-lg border text-xs transition-colors ${
                          editDraft.instrumentation === inst.value
                            ? 'border-gray-900 dark:border-gray-100 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                            : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400'
                        }`}
                      >
                        <div className="font-medium">{inst.label}</div>
                        <div className="text-gray-400 dark:text-gray-500 text-[10px] mt-0.5">{inst.description}</div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Observability metadata */}
                {editDraft.observability_backend && (
                  <div className="space-y-3 pl-3 border-l-2 border-gray-200 dark:border-gray-700">
                    <div className="flex gap-3">
                      <div className="flex-1">
                        <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Service name</label>
                        <input
                          type="text"
                          value={editDraft.service_name}
                          onChange={(e) => setEditDraft((d) => ({ ...d, service_name: e.target.value }))}
                          placeholder="e.g. checkout-api"
                          className="w-full px-2.5 py-1.5 text-xs border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:border-gray-400"
                        />
                      </div>
                      <div className="flex-1">
                        <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Environment</label>
                        <input
                          type="text"
                          value={editDraft.environment}
                          onChange={(e) => setEditDraft((d) => ({ ...d, environment: e.target.value }))}
                          placeholder="e.g. production"
                          className="w-full px-2.5 py-1.5 text-xs border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:border-gray-400"
                        />
                      </div>
                    </div>
                    {(editDraft.observability_backend === 'datadog' || editDraft.observability_backend === 'prometheus' || editDraft.observability_backend === 'grafana') && (
                      <div>
                        <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">
                          {editDraft.observability_backend === 'datadog' ? 'Datadog tags' : 'Prometheus / Grafana labels'}{' '}
                          <span className="text-gray-400">(key → value pairs used to filter telemetry)</span>
                        </label>
                        <div className="space-y-1.5">
                          {editDraft.obs_kv.map((pair, i) => (
                            <div key={i} className="flex items-center gap-2">
                              <input
                                type="text"
                                value={pair.key}
                                onChange={(e) => setEditDraft((d) => {
                                  const kv = [...d.obs_kv]; kv[i] = { ...kv[i], key: e.target.value }; return { ...d, obs_kv: kv }
                                })}
                                placeholder="key"
                                className="w-28 px-2 py-1 text-xs border border-gray-200 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:border-gray-400"
                              />
                              <span className="text-gray-400 text-xs">:</span>
                              <input
                                type="text"
                                value={pair.value}
                                onChange={(e) => setEditDraft((d) => {
                                  const kv = [...d.obs_kv]; kv[i] = { ...kv[i], value: e.target.value }; return { ...d, obs_kv: kv }
                                })}
                                placeholder="value"
                                className="flex-1 px-2 py-1 text-xs border border-gray-200 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:border-gray-400"
                              />
                              <button
                                type="button"
                                onClick={() => setEditDraft((d) => ({ ...d, obs_kv: d.obs_kv.filter((_, j) => j !== i) }))}
                                className="text-gray-400 hover:text-red-500 text-xs px-1"
                              >✕</button>
                            </div>
                          ))}
                          <button
                            type="button"
                            onClick={() => setEditDraft((d) => ({ ...d, obs_kv: [...d.obs_kv, { key: '', value: '' }] }))}
                            className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
                          >+ Add pair</button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Context summary */}
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Context summary</label>
                  <textarea
                    value={editDraft.context_summary}
                    onChange={(e) => setEditDraft((d) => ({ ...d, context_summary: e.target.value }))}
                    rows={3}
                    placeholder="Brief description: what this repo does, service responsibilities, integrations..."
                    className="w-full px-3 py-2 text-xs border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:border-gray-400 resize-none"
                  />
                </div>

                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => saveContextMutation.mutate({ id: repo.id, draft: editDraft })}
                    disabled={saveContextMutation.isPending}
                    className="px-3 py-1.5 text-xs bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50"
                  >
                    {saveContextMutation.isPending ? 'Saving...' : 'Save'}
                  </button>
                  <button
                    onClick={() => setEditingContextId(null)}
                    className="px-3 py-1.5 text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Deactivate confirmation */}
            {confirmDeleteId === repo.id && (
              <div className="mt-3 ml-9 flex items-center gap-3 text-xs text-gray-600 dark:text-gray-400">
                <span>Deactivate <span className="font-medium text-gray-900 dark:text-gray-100">{repo.full_name}</span>? It will be removed from all platform processes.</span>
                <button
                  onClick={() => deactivateMutation.mutate(repo.id)}
                  disabled={deactivateMutation.isPending}
                  className="px-3 py-1.5 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50 shrink-0"
                >
                  {deactivateMutation.isPending ? 'Deactivating...' : 'Deactivate'}
                </button>
                <button
                  onClick={() => setConfirmDeleteId(null)}
                  className="px-3 py-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 shrink-0"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
      </div>

      {/* Analyze now modal — wide layout, scroll body, sticky actions */}
      {analyzeModal && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center sm:items-center bg-black/60 p-0 sm:p-4 md:p-6 overflow-y-auto overscroll-y-contain"
          role="dialog"
          aria-modal="true"
          aria-labelledby="analyze-modal-title"
        >
          <div className="flex flex-col w-full max-w-[min(100%,1280px)] sm:max-h-[min(92dvh,920px)] max-h-[100dvh] min-h-0 bg-white dark:bg-gray-900 shadow-2xl border border-gray-200 dark:border-gray-700 rounded-t-2xl sm:rounded-xl my-0 sm:my-0">
            <div className="shrink-0 flex items-center justify-between gap-4 px-4 sm:px-6 py-4 border-b border-gray-200 dark:border-gray-700">
              <div className="min-w-0">
                <h2
                  id="analyze-modal-title"
                  className="text-base font-semibold text-gray-900 dark:text-gray-100"
                >
                  Analyze repository
                </h2>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 truncate">
                  <RepoWebLink
                    name={analyzeModal.repo.full_name}
                    href={analyzeModal.repo.web_url}
                    className="text-gray-400 dark:text-gray-500 hover:text-blue-500 dark:hover:text-blue-400"
                  />
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setAnalyzeModal(null)
                  setQuickScope([])
                  setSelectAll(true)
                  setEstimate(null)
                }}
                className="shrink-0 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-2xl leading-none w-10 h-10 flex items-center justify-center rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 sm:px-6 py-4 sm:py-5">
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8 xl:gap-10">

                {/* Left column — scope selector */}
                <div className="lg:col-span-7 space-y-5 min-w-0">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-3">
                      Scope
                    </label>

                    {/* Select-all toggle */}
                    <button
                      type="button"
                      onClick={() => { setSelectAll(true); setQuickScope([]) }}
                      className={`w-full flex items-start gap-3 px-4 py-3 rounded-lg border text-left text-xs transition-colors mb-2 ${
                        selectAll
                          ? 'border-gray-900 dark:border-gray-100 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 ring-1 ring-gray-900/10 dark:ring-white/10'
                          : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500'
                      }`}
                    >
                      <span className={`mt-0.5 w-3.5 h-3.5 rounded-full border-2 shrink-0 flex items-center justify-center ${
                        selectAll ? 'border-gray-900 dark:border-gray-100 bg-gray-900 dark:bg-gray-100' : 'border-gray-300 dark:border-gray-600'
                      }`}>
                        {selectAll && <span className="w-1.5 h-1.5 rounded-full bg-white dark:bg-gray-900" />}
                      </span>
                      <div>
                        <div className="font-medium">Analyze all files</div>
                        <div className="text-gray-400 dark:text-gray-500 mt-0.5 leading-snug">
                          Full repo scan — type is chosen automatically based on existing context.
                        </div>
                      </div>
                    </button>

                    {/* Specific paths toggle */}
                    <button
                      type="button"
                      onClick={() => setSelectAll(false)}
                      className={`w-full flex items-start gap-3 px-4 py-3 rounded-lg border text-left text-xs transition-colors ${
                        !selectAll
                          ? 'border-gray-900 dark:border-gray-100 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 ring-1 ring-gray-900/10 dark:ring-white/10'
                          : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500'
                      }`}
                    >
                      <span className={`mt-0.5 w-3.5 h-3.5 rounded-full border-2 shrink-0 flex items-center justify-center ${
                        !selectAll ? 'border-gray-900 dark:border-gray-100 bg-gray-900 dark:bg-gray-100' : 'border-gray-300 dark:border-gray-600'
                      }`}>
                        {!selectAll && <span className="w-1.5 h-1.5 rounded-full bg-white dark:bg-gray-900" />}
                      </span>
                      <div>
                        <div className="font-medium">Select files or folders</div>
                        <div className="text-gray-400 dark:text-gray-500 mt-0.5 leading-snug">
                          Targeted pass on selected paths only — faster and cheaper.
                        </div>
                      </div>
                    </button>
                  </div>

                  {!selectAll && (
                    <div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-2 leading-relaxed">
                        Browse and pick one or more <strong>files</strong> or <strong>folders</strong>. Folders are expanded server-side.
                      </p>
                      <RepoContentsPicker
                        repoId={analyzeModal.repo.id}
                        refName={analyzeBranch.trim() || analyzeModal.repo.default_branch}
                        selection={quickScope}
                        onSelectionChange={setQuickScope}
                        listMaxHeightClassName="max-h-[min(38vh,14rem)] sm:max-h-80 lg:max-h-[min(52vh,26rem)] xl:max-h-[28rem]"
                      />
                      {quickScope.length === 0 && (
                        <p className="text-xs text-amber-800 dark:text-amber-200/90 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900/50 rounded-lg px-3 py-2 mt-2">
                          Select at least one file or folder to continue.
                        </p>
                      )}
                    </div>
                  )}
                </div>

                {/* Right column: LLM + branch */}
                <div className="lg:col-span-5 space-y-5 min-w-0 lg:border-l lg:border-gray-200 dark:lg:border-gray-700 lg:pl-6 xl:pl-8">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
                      Run configuration
                    </p>

                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">
                      LLM Model
                    </label>
                    <div className="grid grid-cols-2 gap-2 mb-4">
                      {([
                        { value: 'anthropic' as const, label: 'Claude', desc: 'Anthropic Claude Sonnet / Haiku' },
                        { value: 'cerebra_ai' as const, label: 'CerebraAI', desc: 'Qwen 3.5 35B (self-hosted)' },
                      ]).map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setSelectedProvider(opt.value)}
                          className={`flex flex-col text-left px-3 py-2.5 rounded-lg border text-xs transition-colors ${
                            selectedProvider === opt.value
                              ? 'border-gray-900 dark:border-gray-100 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 ring-1 ring-gray-900/10 dark:ring-white/10'
                              : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500'
                          }`}
                        >
                          <span className="font-medium">{opt.label}</span>
                          <span className="text-gray-400 dark:text-gray-500 mt-0.5 leading-snug">{opt.desc}</span>
                        </button>
                      ))}
                    </div>

                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">
                      Branch / Tag
                    </label>
                    <select
                      value={analyzeBranch}
                      onChange={(e) => setAnalyzeBranch(e.target.value)}
                      className="w-full px-3 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-400/30 dark:focus:ring-gray-500/30"
                    >
                      {!repoRefs ? (
                        <option value={analyzeModal.repo.default_branch}>{analyzeModal.repo.default_branch}</option>
                      ) : (
                        <>
                          {repoRefs.branches.length > 0 && (
                            <optgroup label="Branches">
                              {repoRefs.branches.map((b) => (
                                <option key={b} value={b}>
                                  {b}
                                </option>
                              ))}
                            </optgroup>
                          )}
                          {repoRefs.tags.length > 0 && (
                            <optgroup label="Tags">
                              {repoRefs.tags.map((t) => (
                                <option key={`tag:${t}`} value={t}>
                                  {t}
                                </option>
                              ))}
                            </optgroup>
                          )}
                        </>
                      )}
                    </select>
                  </div>

                  {/* Estimate info */}
                  {(estimate || estimating) && (
                    <div className="rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-3 text-xs space-y-1.5">
                      <p className="font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide text-[10px]">Estimate</p>
                      {estimating ? (
                        <p className="text-gray-400 dark:text-gray-500 italic">Calculating…</p>
                      ) : estimate ? (
                        <>
                          <p className="text-gray-700 dark:text-gray-300">
                            <span className="font-medium capitalize">{estimate.analysis_type}</span> analysis
                            {estimate.file_count > 0 && (
                              <span className="text-gray-400 dark:text-gray-500"> · {estimate.file_count} path{estimate.file_count !== 1 ? 's' : ''} selected</span>
                            )}
                          </p>
                          <p className="text-gray-500 dark:text-gray-400">
                            ~{estimate.estimated_credits} credit{estimate.estimated_credits !== 1 ? 's' : ''}
                          </p>
                        </>
                      ) : null}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="shrink-0 flex flex-col-reverse sm:flex-row gap-2 sm:gap-3 px-4 sm:px-6 py-4 border-t border-gray-200 dark:border-gray-800 bg-gray-50/90 dark:bg-gray-950/50">
              <button
                type="button"
                onClick={() => {
                  setAnalyzeModal(null)
                  setQuickScope([])
                  setSelectAll(true)
                  setEstimate(null)
                }}
                className="w-full sm:flex-1 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg text-gray-600 dark:text-gray-400 hover:bg-white dark:hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitAnalyze}
                disabled={triggerMutation.isPending || (!selectAll && quickScope.length === 0)}
                className="w-full sm:flex-1 py-2.5 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50"
              >
                {triggerMutation.isPending ? 'Starting...' : 'Start analysis'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add repo modal */}
      {showAdd && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-900 rounded-xl w-full max-w-lg shadow-xl border border-gray-200 dark:border-gray-700 flex flex-col max-h-[90vh]">

            {/* Header — always visible */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
              <div className="flex items-center gap-3">
                <span className={`w-6 h-6 rounded-full text-xs flex items-center justify-center font-medium ${step === 'select' ? 'bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900' : 'bg-gray-200 dark:bg-gray-700 text-gray-500'}`}>1</span>
                <span className={`text-sm ${step === 'select' ? 'font-medium text-gray-900 dark:text-gray-100' : 'text-gray-400'}`}>Select repo</span>
                <span className="text-gray-300 dark:text-gray-600">→</span>
                <span className={`w-6 h-6 rounded-full text-xs flex items-center justify-center font-medium ${step === 'context' ? 'bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900' : 'bg-gray-200 dark:bg-gray-700 text-gray-500'}`}>2</span>
                <span className={`text-sm ${step === 'context' ? 'font-medium text-gray-900 dark:text-gray-100' : 'text-gray-400'}`}>Configure</span>
              </div>
              <button onClick={closeAdd} className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-lg leading-none">×</button>
            </div>

            {/* Step 1 — select repo */}
            {step === 'select' && (
              <div className="flex flex-col flex-1 min-h-0">
                <div className="px-6 pt-5 pb-3 shrink-0">
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {showAddScmPicker
                      ? 'You have more than one SCM connected. Choose which provider to import from.'
                      : 'Choose a repository from a connected provider (GitHub, GitLab, or Bitbucket).'}
                  </p>
                </div>
                {scmConnectionsLoading ? (
                  <div className="text-sm text-gray-400 dark:text-gray-500 text-center py-8 px-6">
                    Loading connections…
                  </div>
                ) : connectedScmTypes.length === 0 ? (
                  <div className="text-sm text-gray-400 dark:text-gray-500 text-center py-6 px-6">
                    No SCM connected. Connect GitHub, GitLab, or Bitbucket in Settings → Connections first.
                  </div>
                ) : showAddScmPicker ? (
                  <div className="px-6 pb-6 space-y-3 flex-1">
                    <div className="grid gap-2">
                      {connectedScmTypes.map((id) => (
                        <button
                          key={id}
                          type="button"
                          onClick={() => {
                            setAddRepoScmChoice(id)
                            setAddRepoSearch('')
                          }}
                          className="flex items-center gap-3 w-full text-left p-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-gray-400 dark:hover:border-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800 text-sm text-gray-900 dark:text-gray-100 transition-colors"
                        >
                          <ScmLogo scm={id} className="h-6 w-6 shrink-0" />
                          <span className="font-medium">{SCM_CHOICE_LABEL[id]}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : availableLoading ? (
                  <div className="text-sm text-gray-400 dark:text-gray-500 text-center py-8 px-6">
                    Loading repositories…
                  </div>
                ) : (
                  <>
                    <div className="px-6 pb-3 shrink-0 space-y-2">
                      {connectedScmTypes.length > 1 && effectiveAddScm && (
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-2">
                            <ScmLogo scm={effectiveAddScm} className="h-4 w-4 shrink-0" />
                            {SCM_CHOICE_LABEL[effectiveAddScm]}
                          </span>
                          <button
                            type="button"
                            onClick={() => {
                              setAddRepoScmChoice(null)
                              setAddRepoSearch('')
                            }}
                            className="text-xs text-blue-600 dark:text-blue-400 hover:underline shrink-0"
                          >
                            Change provider
                          </button>
                        </div>
                      )}
                      <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                        <input
                          type="search"
                          value={addRepoSearch}
                          onChange={(e) => setAddRepoSearch(e.target.value)}
                          placeholder="Search by repository name…"
                          className="w-full pl-9 pr-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-400 dark:focus:ring-gray-500"
                          autoComplete="off"
                        />
                      </div>
                    </div>
                    {reposForSelectedScm.length === 0 ? (
                      <div className="text-sm text-gray-400 dark:text-gray-500 text-center py-6 px-6">
                        No repositories available for this account.
                      </div>
                    ) : filteredAvailableRepos.length === 0 ? (
                      <div className="text-sm text-gray-400 dark:text-gray-500 text-center py-6 px-6">
                        No repositories match your search.
                      </div>
                    ) : (
                      <div className="flex-1 overflow-y-auto px-6 space-y-1.5 pr-5 min-h-0">
                        {filteredAvailableRepos.map((r: PendingRepo) => {
                          const st = r.scm_type || 'github'
                          const browseUrl =
                            r.html_url ??
                            (r.clone_url?.replace(/\.git$/, '') ||
                              (st === 'gitlab'
                                ? `https://gitlab.com/${r.full_name}`
                                : st === 'bitbucket'
                                  ? `https://bitbucket.org/${r.full_name}`
                                  : `https://github.com/${r.full_name}`))
                          return (
                            <div
                              key={`${st}-${r.scm_repo_id}`}
                              role="button"
                              tabIndex={0}
                              onClick={() => handleSelectRepo(r)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault()
                                  handleSelectRepo(r)
                                }
                              }}
                              className="w-full text-left p-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-gray-400 dark:hover:border-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800 text-sm text-gray-900 dark:text-gray-100 transition-colors flex items-center justify-between gap-2"
                            >
                              <ScmLogo scm={st} className="h-5 w-5 shrink-0 opacity-80" />
                              <span className="min-w-0 flex-1">
                                <a
                                  href={browseUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="font-medium hover:underline hover:text-blue-600 dark:hover:text-blue-400"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  {r.full_name}
                                </a>
                                <span className="text-xs text-gray-400 dark:text-gray-500 ml-2">{r.default_branch}</span>
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </>
                )}
                {/* Footer — always visible */}
                <div className="px-6 pb-5 pt-3 shrink-0">
                  <button onClick={closeAdd} className="w-full py-2 text-sm text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Step 2 — configure context */}
            {step === 'context' && pending && (
              <div className="flex flex-col flex-1 min-h-0">

                {/* Scrollable form body */}
                <div className="flex-1 overflow-y-auto px-6 pt-5 pb-2 space-y-4">
                  <div className="flex items-center gap-2">
                    <ScmLogo scm={pending.scm_type || 'github'} className="w-4 h-4" />
                    <RepoWebLink
                      name={pending.full_name}
                      href={
                        pending.html_url ??
                        (pending.clone_url?.replace(/\.git$/, '') ||
                          (pending.scm_type === 'gitlab'
                            ? `https://gitlab.com/${pending.full_name}`
                            : pending.scm_type === 'bitbucket'
                              ? `https://bitbucket.org/${pending.full_name}`
                              : `https://github.com/${pending.full_name}`))
                      }
                      className="text-sm font-medium"
                    />
                  </div>

                  <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                    This context helps Horion tailor its analysis. All fields are optional — you can update them later.
                  </p>

                  {/* Repo type */}
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Repository type</label>
                    <div className="grid grid-cols-2 gap-2">
                      {REPO_TYPES.map((t) => (
                        <button
                          key={t.value}
                          type="button"
                          onClick={() => setContext((c) => ({ ...c, repo_type: c.repo_type === t.value ? '' : t.value, app_subtype: '', iac_provider: '' }))}
                          className={`text-left p-3 rounded-lg border text-xs transition-colors ${
                            context.repo_type === t.value
                              ? 'border-gray-900 dark:border-gray-100 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                              : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500'
                          }`}
                        >
                          <div className="font-medium mb-0.5">{t.label}</div>
                          <div className="text-gray-400 dark:text-gray-500">{t.description}</div>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* App subtype */}
                  {context.repo_type === 'app' && (
                    <div>
                      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Application type</label>
                      <div className="flex flex-wrap gap-2">
                        {APP_SUBTYPES.map((s) => (
                          <button
                            key={s.value}
                            type="button"
                            onClick={() => setContext((c) => ({ ...c, app_subtype: c.app_subtype === s.value ? '' : s.value }))}
                            className={`px-3 py-1 rounded text-xs border transition-colors ${
                              context.app_subtype === s.value
                                ? 'border-gray-900 dark:border-gray-100 bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium'
                                : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400'
                            }`}
                          >{s.label}</button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* IaC provider */}
                  {context.repo_type === 'iac' && (
                    <div>
                      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Cloud provider</label>
                      <div className="flex flex-wrap gap-2">
                        {IAC_PROVIDERS.map((p) => (
                          <button
                            key={p.value}
                            type="button"
                            onClick={() => setContext((c) => ({ ...c, iac_provider: c.iac_provider === p.value ? '' : p.value }))}
                            className={`px-3 py-1 rounded text-xs border transition-colors ${
                              context.iac_provider === p.value
                                ? 'border-gray-900 dark:border-gray-100 bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium'
                                : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400'
                            }`}
                          >{p.label}</button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Language */}
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Primary language</label>
                    <div className="flex flex-wrap gap-2">
                      {LANGUAGES.map((lang) => (
                        <button
                          key={lang}
                          type="button"
                          onClick={() => setContext((c) => ({
                            ...c,
                            languages: c.languages.includes(lang)
                              ? c.languages.filter((l) => l !== lang)
                              : [...c.languages, lang],
                          }))}
                          className={`px-3 py-1 rounded text-xs border transition-colors ${
                            context.languages.includes(lang)
                              ? 'border-gray-900 dark:border-gray-100 bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium'
                              : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500'
                          }`}
                        >
                          {lang}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Observability backend */}
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Observability backend</label>
                    <p className="text-xs text-gray-400 dark:text-gray-500 mb-2">Where your metrics/traces are sent.</p>
                    <div className="flex flex-wrap gap-2">
                      {OBS_BACKENDS.map((b) => (
                        <button
                          key={b.value}
                          type="button"
                          onClick={() => setContext((c) => ({ ...c, observability_backend: c.observability_backend === b.value ? '' : b.value, obs_kv: [] }))}
                          className={`px-3 py-1 rounded text-xs border transition-colors ${
                            context.observability_backend === b.value
                              ? 'border-gray-900 dark:border-gray-100 bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium'
                              : 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500'
                          }`}
                        >
                          {b.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Instrumentation */}
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">Instrumentation library</label>
                    <div className="grid grid-cols-3 gap-2">
                      {INSTRUMENTATIONS.map((inst) => (
                        <button
                          key={inst.value}
                          type="button"
                          onClick={() => setContext((c) => ({ ...c, instrumentation: c.instrumentation === inst.value ? '' : inst.value }))}
                          className={`text-left p-2.5 rounded-lg border text-xs transition-colors ${
                            context.instrumentation === inst.value
                              ? 'border-gray-900 dark:border-gray-100 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
                              : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500'
                          }`}
                        >
                          <div className="font-medium">{inst.label}</div>
                          <div className="text-gray-400 dark:text-gray-500 text-[10px] mt-0.5">{inst.description}</div>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Observability metadata */}
                  {context.observability_backend && (
                    <div className="pl-3 border-l-2 border-gray-200 dark:border-gray-700 space-y-3">
                      <div className="flex gap-3">
                        <div className="flex-1">
                          <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Service name</label>
                          <input
                            type="text"
                            value={context.service_name}
                            onChange={(e) => setContext((c) => ({ ...c, service_name: e.target.value }))}
                            placeholder="e.g. checkout-api"
                            className="w-full px-2.5 py-1.5 text-xs border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:border-gray-400"
                          />
                        </div>
                        <div className="flex-1">
                          <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">Environment</label>
                          <input
                            type="text"
                            value={context.environment}
                            onChange={(e) => setContext((c) => ({ ...c, environment: e.target.value }))}
                            placeholder="e.g. production"
                            className="w-full px-2.5 py-1.5 text-xs border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:border-gray-400"
                          />
                        </div>
                      </div>
                      {(context.observability_backend === 'datadog' || context.observability_backend === 'prometheus' || context.observability_backend === 'grafana') && (
                        <div>
                          <label className="block text-xs text-gray-500 dark:text-gray-400 mb-1">
                            {context.observability_backend === 'datadog' ? 'Datadog tags' : 'Prometheus / Grafana labels'}
                          </label>
                          <div className="space-y-1.5">
                            {context.obs_kv.map((pair, i) => (
                              <div key={i} className="flex items-center gap-2">
                                <input
                                  type="text"
                                  value={pair.key}
                                  onChange={(e) => setContext((c) => {
                                    const kv = [...c.obs_kv]; kv[i] = { ...kv[i], key: e.target.value }; return { ...c, obs_kv: kv }
                                  })}
                                  placeholder="key"
                                  className="w-24 px-2 py-1 text-xs border border-gray-200 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none"
                                />
                                <span className="text-gray-400 text-xs">:</span>
                                <input
                                  type="text"
                                  value={pair.value}
                                  onChange={(e) => setContext((c) => {
                                    const kv = [...c.obs_kv]; kv[i] = { ...kv[i], value: e.target.value }; return { ...c, obs_kv: kv }
                                  })}
                                  placeholder="value"
                                  className="flex-1 px-2 py-1 text-xs border border-gray-200 dark:border-gray-700 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none"
                                />
                                <button type="button" onClick={() => setContext((c) => ({ ...c, obs_kv: c.obs_kv.filter((_, j) => j !== i) }))} className="text-gray-400 hover:text-red-500 text-xs px-1">✕</button>
                              </div>
                            ))}
                            <button
                              type="button"
                              onClick={() => setContext((c) => ({ ...c, obs_kv: [...c.obs_kv, { key: '', value: '' }] }))}
                              className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
                            >+ Add pair</button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Footer — always visible, pinned below scroll area */}
                <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 shrink-0">
                  <div className="flex gap-3">
                    <button
                      onClick={() => setStep('select')}
                      className="flex-1 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
                    >
                      Back
                    </button>
                    <button
                      onClick={handleFinish}
                      disabled={activateMutation.isPending}
                      className="flex-1 py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg font-medium hover:bg-gray-700 dark:hover:bg-gray-300 disabled:opacity-50"
                    >
                      {activateMutation.isPending ? 'Adding...' : 'Add repository'}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
