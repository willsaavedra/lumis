'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reposApi, analysesApi, Repository, connectionsApi, type ScmConnection } from '@/lib/api'
import { RepoWebLink } from '@/components/RepoWebLink'
import { ScmLogo } from '@/components/ScmLogo'
import { LanguageLogo } from '@/components/LanguageLogo'
import { ObsBackendLogo } from '@/components/ObsBackendLogo'
import { formatDate } from '@/lib/utils'
import { useState, useRef, useEffect, useMemo } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { ExternalLink, Search } from 'lucide-react'
import { RepoContentsPicker, resolveScopeAnalysisType, type ScopeItem } from '@/components/RepoContentsPicker'
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
  const [analyzeType, setAnalyzeType] = useState<'quick' | 'full' | 'repository'>('full')
  const [analyzeBranch, setAnalyzeBranch] = useState('')
  const [quickScope, setQuickScope] = useState<ScopeItem[]>([])
  const [editingContextId, setEditingContextId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<ContextForm>(EMPTY_CONTEXT)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [contextDiscoveryRepoId, setContextDiscoveryRepoId] = useState<string | null>(null)
  const [contextDiscoveryJobId, setContextDiscoveryJobId] = useState<string | null>(null)
  const [addRepoScmChoice, setAddRepoScmChoice] = useState<ScmChoiceId | null>(null)
  const [addRepoSearch, setAddRepoSearch] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

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
      type: string
      changedFiles?: string[] | null
    }) => {
      setAnalyzingId(payload.repoId)
      return analysesApi.trigger(payload.repoId, payload.ref, payload.type, payload.changedFiles ?? null)
    },
    onSuccess: (data) => {
      toast('Analysis started — results will appear in Analyses', 'success')
      setAnalyzingId(null)
      setAnalyzeModal(null)
      setQuickScope([])
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
    setAnalyzeType('full')
    setAnalyzeBranch(repo.default_branch)
    setQuickScope([])
  }

  function submitAnalyze() {
    if (!analyzeModal) return
    if (analyzeType === 'quick' && quickScope.length === 0) return
    const resolved = resolveScopeAnalysisType(analyzeType, quickScope)
    triggerMutation.mutate({
      repoId: analyzeModal.repo.id,
      ref: analyzeBranch.trim() || analyzeModal.repo.default_branch,
      type: resolved.analysisType,
      changedFiles: resolved.changedFiles,
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

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Repositories</h1>
          <p className="text-gray-500 dark:text-gray-400">Manage repositories for analysis</p>
        </div>
        <button
          onClick={openAdd}
          className="px-4 py-2 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 rounded-lg text-sm font-medium hover:bg-gray-700 dark:hover:bg-gray-300"
        >
          + Add repository
        </button>
      </div>

      {/* Repo list */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-800">
        {repos?.length === 0 && (
          <div className="p-8 text-center text-gray-400 dark:text-gray-500 text-sm">
            No repositories yet. Connect GitHub to get started.
          </div>
        )}
        {repos?.map((repo) => (
          <div key={repo.id} className="p-4">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 min-w-0">
                <ScmLogo scm={repo.scm_type} className="h-6 w-6 shrink-0" />
                <div className="min-w-0">
                  <div className="font-medium text-gray-900 dark:text-gray-100 text-sm truncate flex items-center gap-2">
                    <Link
                      href={`/repositories/${repo.id}`}
                      className="truncate hover:underline text-gray-900 dark:text-gray-100"
                    >
                      {repo.full_name}
                    </Link>
                    <a
                      href={repo.web_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Open on Git host"
                      className="shrink-0 text-gray-400 hover:text-blue-600 dark:hover:text-blue-400"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                    </a>
                    {contextDiscoveryRepoId === repo.id && (
                      <span className="flex items-center gap-1 text-xs text-gray-400 dark:text-gray-500 font-normal">
                        <span className="w-3 h-3 border border-gray-400 border-t-transparent rounded-full animate-spin" />
                        analyzing context...
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
                    <span>{repo.default_branch}</span>
                    <span>·</span>
                    <span>added {formatDate(repo.created_at)}</span>
                    {repo.last_analysis_at && (
                      <>
                        <span>·</span>
                        <span>last analysis {formatDate(repo.last_analysis_at)}</span>
                      </>
                    )}
                    {repo.repo_type && (
                      <>
                        <span>·</span>
                        <span className="capitalize">
                          {repo.repo_type === 'app' && repo.app_subtype
                            ? `app / ${repo.app_subtype.replace('_', ' ')}`
                            : repo.repo_type === 'iac' && repo.iac_provider
                            ? `iac / ${repo.iac_provider.toUpperCase()}`
                            : repo.repo_type}
                        </span>
                      </>
                    )}
                    {repo.language && repo.language.length > 0 && (
                      <>
                        <span>·</span>
                        {repo.language.map((lang) => (
                          <span key={lang} className="flex items-center gap-1">
                            <LanguageLogo language={lang} />{lang}
                          </span>
                        ))}
                      </>
                    )}
                    {repo.observability_backend && (
                      <><span>·</span><ObsBackendLogo backend={repo.observability_backend} /><span className="capitalize">{repo.observability_backend}</span></>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => {
                    if (editingContextId === repo.id) {
                      setEditingContextId(null)
                    } else {
                      setEditingContextId(repo.id)
                      setEditDraft(repoToContextForm(repo))
                      setConfirmDeleteId(null)
                    }
                  }}
                  className="px-3 py-1.5 text-xs border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 font-medium"
                >
                  Edit context
                </button>
                <button
                  onClick={() => openAnalyzeModal(repo)}
                  disabled={analyzingId === repo.id}
                  className="px-3 py-1.5 text-xs bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 font-medium disabled:opacity-50 flex items-center gap-1.5"
                >
                  {analyzingId === repo.id ? (
                    <><span className="w-3 h-3 border border-gray-400 border-t-transparent rounded-full animate-spin" />Analyzing...</>
                  ) : 'Analyze now'}
                </button>
                <button
                  onClick={() => { setConfirmDeleteId(repo.id); setEditingContextId(null) }}
                  className="px-2 py-1.5 text-xs text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800"
                  title="Remove repository"
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Context summary — inline view */}
            {repo.context_summary && editingContextId !== repo.id && (
              <div className="mt-3 ml-9 text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg px-3 py-2 leading-relaxed line-clamp-2">
                {repo.context_summary}
              </div>
            )}

            {/* Full context edit panel */}
            {editingContextId === repo.id && (
              <div className="mt-3 ml-9 border border-gray-200 dark:border-gray-700 rounded-xl p-4 space-y-4 bg-gray-50 dark:bg-gray-800/50">
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
                }}
                className="shrink-0 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-2xl leading-none w-10 h-10 flex items-center justify-center rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 sm:px-6 py-4 sm:py-5">
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8 xl:gap-10">
                <div className="lg:col-span-7 space-y-5 min-w-0">
              {/* Comparison table — explicit differences */}
              <details
                open
                className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-800/40 overflow-hidden"
              >
                <summary className="cursor-pointer list-none px-3 py-2.5 text-xs font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2 marker:content-none">
                  <span className="text-gray-400 dark:text-gray-500 select-none" aria-hidden>
                    ▾
                  </span>
                  <span>Compare analysis types</span>
                </summary>
                <div className="overflow-x-auto border-t border-gray-200 dark:border-gray-700 px-2 pb-2 -mx-0">
                  <table className="w-full text-[10px] sm:text-xs md:text-sm text-left border-collapse table-fixed min-w-0">
                    <thead>
                      <tr className="border-b border-gray-200 dark:border-gray-600">
                        <th className="py-2 pr-2 font-medium text-gray-500 dark:text-gray-400 align-bottom w-[22%] min-w-[6rem]" />
                        <th className="py-2 px-1.5 font-semibold text-gray-900 dark:text-gray-100 align-bottom w-[26%]">
                          Quick
                        </th>
                        <th className="py-2 px-1.5 font-semibold text-gray-900 dark:text-gray-100 align-bottom w-[26%]">
                          Full
                        </th>
                        <th className="py-2 pl-1.5 font-semibold text-gray-900 dark:text-gray-100 align-bottom w-[26%]">
                          Repository
                        </th>
                      </tr>
                    </thead>
                    <tbody className="text-gray-700 dark:text-gray-300 [&_td]:break-words">
                      <tr className="border-b border-gray-100 dark:border-gray-700/80">
                        <td className="py-1.5 pr-2 font-medium text-gray-600 dark:text-gray-400">Path scope</td>
                        <td className="py-1.5 px-1.5 align-top">Required — only files/folders you select</td>
                        <td className="py-1.5 px-1.5 align-top">Optional — empty = whole clone</td>
                        <td className="py-1.5 pl-1.5 align-top">Optional — empty = deep scan of the codebase</td>
                      </tr>
                      <tr className="border-b border-gray-100 dark:border-gray-700/80">
                        <td className="py-1.5 pr-2 font-medium text-gray-600 dark:text-gray-400">Files considered</td>
                        <td className="py-1.5 px-1.5 align-top">Expanded selection only (fast pass)</td>
                        <td className="py-1.5 px-1.5 align-top">Repo walk, breadth-capped</td>
                        <td className="py-1.5 pl-1.5 align-top">
                          Large set — prioritizes <code className="font-mono text-[9px]">src/</code>,{' '}
                          <code className="font-mono text-[9px]">cmd/</code>, app dirs, then rest
                        </td>
                      </tr>
                      <tr className="border-b border-gray-100 dark:border-gray-700/80">
                        <td className="py-1.5 pr-2 font-medium text-gray-600 dark:text-gray-400">Pipeline</td>
                        <td className="py-1.5 px-1.5 align-top">Skips AST, Datadog pull &amp; RAG — goes straight to coverage LLM</td>
                        <td className="py-1.5 px-1.5 align-top">AST → Datadog → RAG → coverage → efficiency</td>
                        <td className="py-1.5 pl-1.5 align-top">Same full pipeline as Full, on many more files</td>
                      </tr>
                      <tr className="border-b border-gray-100 dark:border-gray-700/80">
                        <td className="py-1.5 pr-2 font-medium text-gray-600 dark:text-gray-400">Coverage model</td>
                        <td className="py-1.5 px-1.5 align-top">Triage / cheaper model, batched</td>
                        <td className="py-1.5 px-1.5 align-top">Primary model</td>
                        <td className="py-1.5 pl-1.5 align-top">Primary model, many batches</td>
                      </tr>
                      <tr>
                        <td className="py-1.5 pr-2 font-medium text-gray-600 dark:text-gray-400">Credits</td>
                        <td className="py-1.5 px-1.5 align-top">1</td>
                        <td className="py-1.5 px-1.5 align-top">3</td>
                        <td className="py-1.5 pl-1.5 align-top">15</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </details>

              {/* Analysis type */}
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">
                  Analysis type
                </label>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                  {([
                    {
                      value: 'quick',
                      label: 'Quick',
                      desc: 'Targeted pass on your selection only — cheapest, no AST/RAG',
                      credits: 1,
                    },
                    {
                      value: 'full',
                      label: 'Full',
                      desc: 'Standard PR-style analysis — full graph, context and efficiency',
                      credits: 3,
                    },
                    {
                      value: 'repository',
                      label: 'Repository',
                      desc: 'Widest file set — best for org-wide instrumentation audit',
                      credits: 15,
                    },
                  ] as const).map((t) => (
                    <button
                      key={t.value}
                      type="button"
                      onClick={() => setAnalyzeType(t.value)}
                      className={`w-full min-h-[5.5rem] md:min-h-[9rem] flex flex-col text-left px-3 py-2.5 rounded-lg border text-xs transition-colors ${
                        analyzeType === t.value
                          ? 'border-gray-900 dark:border-gray-100 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 ring-1 ring-gray-900/10 dark:ring-white/10'
                          : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-1 w-full">
                        <span className="font-medium">{t.label}</span>
                        <span className="shrink-0 text-[10px] text-gray-400 dark:text-gray-500">
                          {t.credits} cr
                        </span>
                      </div>
                      <div className="text-gray-400 dark:text-gray-500 mt-1 leading-snug flex-1">{t.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Selected type — explicit recap */}
              <div
                className={`rounded-lg border px-3 py-2.5 text-[11px] leading-relaxed ${
                  analyzeType === 'quick'
                    ? 'border-blue-200 dark:border-blue-900/50 bg-blue-50/90 dark:bg-blue-950/25 text-blue-950 dark:text-blue-100/95'
                    : analyzeType === 'full'
                      ? 'border-violet-200 dark:border-violet-900/50 bg-violet-50/90 dark:bg-violet-950/25 text-violet-950 dark:text-violet-100/95'
                      : 'border-amber-200 dark:border-amber-900/50 bg-amber-50/90 dark:bg-amber-950/25 text-amber-950 dark:text-amber-100/95'
                }`}
              >
                <p className="font-semibold mb-1">
                  {analyzeType === 'quick' && 'Quick — what will run'}
                  {analyzeType === 'full' && 'Full — what will run'}
                  {analyzeType === 'repository' && 'Repository — what will run'}
                </p>
                <ul className="list-disc pl-4 space-y-0.5 text-[11px] opacity-95">
                  {analyzeType === 'quick' && (
                    <>
                      <li>Analysis is limited to the paths you select below (folders are expanded server-side).</li>
                      <li>No call-graph / AST step, no Datadog metadata fetch, no RAG docs — faster feedback on specific code.</li>
                      <li>Coverage findings use the triage model in small batches.</li>
                    </>
                  )}
                  {analyzeType === 'full' && (
                    <>
                      <li>Clone the branch, walk the repo (or only paths if you set a scope).</li>
                      <li>Builds AST / call graph, may pull Datadog signals, enriches with RAG, then coverage + efficiency scoring.</li>
                      <li>Best default for ongoing PRs and full observability review.</li>
                    </>
                  )}
                  {analyzeType === 'repository' && (
                    <>
                      <li>Deep scan: many files, ordered so application code (e.g. <code className="font-mono text-[10px] px-0.5 rounded bg-black/5 dark:bg-white/10">src/</code>) is seen first.</li>
                      <li>Same rich pipeline as Full — expect higher LLM usage and longer runtime.</li>
                      <li>Use for periodic org-wide or baseline instrumentation audits.</li>
                    </>
                  )}
                </ul>
              </div>
                </div>

                {/* Right column: branch + path scope — uses horizontal space on large screens */}
                <div className="lg:col-span-5 space-y-5 min-w-0 lg:border-l lg:border-gray-200 dark:lg:border-gray-700 lg:pl-6 xl:pl-8">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-3">
                      Run configuration
                    </p>
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

                  {(analyzeType === 'quick' || analyzeType === 'full' || analyzeType === 'repository') && (
                    <div>
                      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide mb-2">
                        {analyzeType === 'quick' ? 'Scope (required)' : 'Path scope (optional)'}
                      </label>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-2 leading-relaxed">
                        {analyzeType === 'quick' && (
                          <>
                            Browse and select one or more <strong>files</strong> or <strong>folders</strong>. Analysis runs{' '}
                            <strong>only</strong> on these paths (folders are expanded on the server).
                          </>
                        )}
                        {analyzeType === 'full' && (
                          <>
                            Leave empty to analyze the <strong>entire</strong> cloned repository. Or select paths to focus the
                            run.
                          </>
                        )}
                        {analyzeType === 'repository' && (
                          <>
                            Leave empty for a <strong>deep</strong> scan of the codebase (walks app source trees like{' '}
                            <code className="text-[10px] font-mono bg-gray-100 dark:bg-gray-800 px-1 rounded">src/</code>{' '}
                            first, then the rest). Or select paths to narrow the scan.
                          </>
                        )}
                      </p>
                      <RepoContentsPicker
                        repoId={analyzeModal.repo.id}
                        refName={analyzeBranch.trim() || analyzeModal.repo.default_branch}
                        selection={quickScope}
                        onSelectionChange={setQuickScope}
                        listMaxHeightClassName="max-h-[min(38vh,14rem)] sm:max-h-80 lg:max-h-[min(52vh,26rem)] xl:max-h-[28rem]"
                      />
                      {analyzeType === 'quick' && quickScope.length === 0 && (
                        <p className="text-xs text-amber-800 dark:text-amber-200/90 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900/50 rounded-lg px-3 py-2 mt-2">
                          Select at least one file or folder — quick analysis cannot run without a scope.
                        </p>
                      )}
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
                }}
                className="w-full sm:flex-1 py-2.5 text-sm border border-gray-200 dark:border-gray-700 rounded-lg text-gray-600 dark:text-gray-400 hover:bg-white dark:hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitAnalyze}
                disabled={triggerMutation.isPending || (analyzeType === 'quick' && quickScope.length === 0)}
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
                    This context helps Lumis tailor its analysis. All fields are optional — you can update them later.
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
