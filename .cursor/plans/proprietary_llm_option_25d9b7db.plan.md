---
name: Proprietary LLM Option
overview: Adicionar CerebraAI (Qwen/OpenAI-compatible) como alternativa ao Claude, com seleção de modelo por análise — persistida no AnalysisJob e escolhida pelo usuário no modal de trigger.
todos:
  - id: db-migration
    content: Criar migration SQL para adicionar coluna `llm_provider TEXT NOT NULL DEFAULT 'anthropic'` em `analysis_jobs`
    status: completed
  - id: orm-model
    content: Adicionar campo `llm_provider` ao SQLAlchemy model `AnalysisJob` em apps/api/models/analysis.py
    status: completed
  - id: config-env
    content: Estender AgentSettings (apps/agent/core/config.py) E api Settings (apps/api/core/config.py) com base_url, api_key, modelos, temperature/top_p e timeout do CerebraAI
    status: completed
  - id: llm-adapter
    content: Criar apps/agent/llm/chat_completion.py com função async única (rota Anthropic SDK vs POST /v1/chat/completions via httpx)
    status: completed
  - id: api-request
    content: "Adicionar `llm_provider: Literal['anthropic','cerebra_ai'] = 'anthropic'` a TriggerAnalysisRequest e passá-lo ao enqueue_manual_analysis → AnalysisJob"
    status: completed
  - id: agent-state
    content: Ler job.llm_provider em apps/agent/graph.py e injetar em state['request']['llm_provider']
    status: completed
  - id: refactor-nodes
    content: Migrar analyze_coverage, generate_suggestions, context_discovery, pre_triage para usar o adapter com o provider do state
    status: completed
  - id: refactor-fix-pr
    content: Migrar fix_pr_service._generate_fixed_file para o adapter; passar llm_provider do job ao caller
    status: completed
  - id: preflight-pretriage
    content: Implementar prompt alternativo sem assistant-prefill para caminho cerebra_ai
    status: completed
  - id: log-cost
    content: Ajustar log_llm_call para custo 0 quando provider=cerebra_ai (self-hosted)
    status: completed
  - id: frontend-ui
    content: Adicionar seletor de modelo no modal de análise (repositories/page.tsx) e passar llm_provider na chamada trigger
    status: completed
  - id: docs-env
    content: Documentar variáveis em .env.local.example e notas de rede do worker
    status: completed
isProject: false
---

# Plano: CerebraAI como opção de LLM — seleção por análise na UI

## Contexto e padrão de design

O campo `analysis_type` usa o padrão correto: **Frontend → API body → `AnalysisJob` (DB) → agente lê do banco → nodes usam do state**. O `llm_provider` vai seguir exatamente este mesmo padrão.

Hoje todas as chamadas de chat usam Anthropic em dois grupos:

**Grupo 1 — nós do agente** (`apps/agent/core/config.py`)

| Arquivo | Cliente atual |
|---------|---------------|
| [`apps/agent/nodes/analyze_coverage.py`](apps/agent/nodes/analyze_coverage.py) | `Anthropic` (sync) — JSON array de findings |
| [`apps/agent/nodes/generate_suggestions.py`](apps/agent/nodes/generate_suggestions.py) | `Anthropic` (sync) — JSON array de sugestões |
| [`apps/agent/nodes/context_discovery.py`](apps/agent/nodes/context_discovery.py) | `Anthropic` (sync) — texto livre |
| [`apps/agent/nodes/pre_triage.py`](apps/agent/nodes/pre_triage.py) | `Anthropic` (sync) — usa **assistant prefill** `"["` para forçar JSON |

**Grupo 2 — fix PR** (`apps/api/core/config.py`)

| Arquivo | Cliente atual | Particularidade |
|---------|---------------|-----------------|
| [`apps/api/services/fix_pr_service.py`](apps/api/services/fix_pr_service.py) | `AsyncAnthropic` | `max_tokens=8000`, retorna texto puro (arquivo completo) |

---

## Fluxo end-to-end do novo campo `llm_provider`

```mermaid
flowchart LR
  modal["Modal UI\n(repositories/page.tsx)\nradio: Claude / CerebraAI"]
  api["POST /api/v1/analyses\nTriggerAnalysisRequest\nllm_provider field"]
  db["analysis_jobs\nllm_provider TEXT\nDEFAULT 'anthropic'"]
  graph["apps/agent/graph.py\nstate['request']['llm_provider']"]
  nodes["Agent nodes\nanalyze_coverage\ngenerate_suggestions\ncontext_discovery\npre_triage"]
  adapter["chat_complete()\napps/agent/llm/chat_completion.py"]
  claude["Anthropic API"]
  cerebra["CerebraAI vLLM\n(Qwen/Qwen3.5-35B-A3B-FP8)"]

  modal -->|"llm_provider"| api
  api -->|"persiste"| db
  db -->|"job.llm_provider"| graph
  graph --> nodes
  nodes --> adapter
  adapter -->|"provider=anthropic"| claude
  adapter -->|"provider=cerebra_ai"| cerebra
```

---

## Mudanças por camada

### 1. Banco de dados — migration

Novo arquivo `infra/migrations/004_llm_provider.sql`:

```sql
ALTER TABLE analysis_jobs
  ADD COLUMN IF NOT EXISTS llm_provider TEXT NOT NULL DEFAULT 'anthropic';
```

Sem enum — texto simples dá flexibilidade para adicionar provedores futuros sem nova migration de ENUM.

### 2. ORM — `AnalysisJob`

Em [`apps/api/models/analysis.py`](apps/api/models/analysis.py), adicionar após `analysis_type`:

```python
llm_provider: Mapped[str] = mapped_column(Text, nullable=False, default="anthropic")
```

### 3. Config — dois arquivos, mesmo bloco de env

Ambos os arquivos de config leem do mesmo `.env.local`, então as vars são declaradas uma vez. Adicionar em [`apps/agent/core/config.py`](apps/agent/core/config.py) **e** em [`apps/api/core/config.py`](apps/api/core/config.py):

```python
# CerebraAI (OpenAI-compatible vLLM — Qwen)
cerebra_ai_base_url: str = "http://52.86.35.131:8001/v1"
cerebra_ai_api_key: str = ""          # sem auth por padrão
cerebra_ai_model_primary: str = "Qwen/Qwen3.5-35B-A3B-FP8"
cerebra_ai_model_triage: str = "Qwen/Qwen3.5-35B-A3B-FP8"
cerebra_ai_temperature: float = 0.4
cerebra_ai_top_p: float = 0.9
cerebra_ai_timeout: int = 300         # segundos — fix_pr pode usar max_tokens=8000
```

> A env var `ANALYSIS_LLM_PROVIDER` **não** é mais necessária como default global — o provider vem sempre do `AnalysisJob` (per análise).

### 4. Adaptador unificado — `apps/agent/llm/chat_completion.py`

Novo módulo com uma única função `async`:

```python
@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int

async def chat_complete(
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    *,
    provider: str,          # "anthropic" | "cerebra_ai"
    base_url: str = "",
    api_key: str = "",
    temperature: float = 0.3,
    top_p: float = 0.9,
    timeout: int = 120,
) -> LLMResponse
```

- **`anthropic`** → `anthropic.AsyncAnthropic(api_key=api_key).messages.create(...)`
- **`cerebra_ai`** → `httpx.AsyncClient.post(f"{base_url}/chat/completions", json={model, messages, stream:false, temperature, top_p, max_tokens})`; lê `usage.prompt_tokens` / `usage.completion_tokens`

### 5. API — `TriggerAnalysisRequest` e serviço

Em [`apps/api/routers/analyses.py`](apps/api/routers/analyses.py):

```python
class TriggerAnalysisRequest(BaseModel):
    repo_id: str
    ref: str = "main"
    analysis_type: str = "full"
    llm_provider: Literal["anthropic", "cerebra_ai"] = "anthropic"   # NOVO
    changed_files: list[str] | None = Field(default=None, ...)
```

Em [`apps/api/services/analysis_service.py`](apps/api/services/analysis_service.py), adicionar `llm_provider` na criação do `AnalysisJob`:

```python
job = AnalysisJob(
    ...
    analysis_type=analysis_type,
    llm_provider=llm_provider,   # NOVO
    ...
)
```

### 6. Agente — leitura do state

Em [`apps/agent/graph.py`](apps/agent/graph.py), adicionar ao `initial_state["request"]`:

```python
"llm_provider": job.llm_provider,   # "anthropic" | "cerebra_ai"
```

### 7. Nós do agente — usar o adapter

Cada nó lê `state["request"]["llm_provider"]` e seleciona o model e params corretos:

```python
from apps.agent.llm.chat_completion import chat_complete

provider = state["request"]["llm_provider"]
model = (
    settings.anthropic_model_primary
    if provider == "anthropic"
    else settings.cerebra_ai_model_primary
)
resp = await chat_complete(
    system=system_prompt,
    user=user_prompt,
    model=model,
    max_tokens=4096,
    provider=provider,
    base_url=settings.cerebra_ai_base_url,
    api_key=settings.cerebra_ai_api_key,
    temperature=settings.cerebra_ai_temperature,
    top_p=settings.cerebra_ai_top_p,
    timeout=settings.cerebra_ai_timeout,
)
```

**`pre_triage` — prompt sem prefill para CerebraAI:**

No caminho `cerebra_ai`, substituir o truque `assistant: "["` por system prompt reforçado:

```
"Return ONLY a valid JSON array. No markdown fences, no explanation. Start directly with [."
```

O parser de resposta já faz strip de fences; sem mudança no downstream.

### 8. Fix PR — adapter + llm_provider do job

[`apps/api/services/fix_pr_service.py`](apps/api/services/fix_pr_service.py) precisa saber o provider. O caller (endpoint de fix PR) tem acesso ao job — passar `llm_provider` como parâmetro para `_generate_fixed_file`:

```python
async def _generate_fixed_file(
    original: str,
    file_path: str,
    findings: list,
    llm_provider: str = "anthropic",   # NOVO
) -> str:
    from apps.agent.llm.chat_completion import chat_complete
    from apps.api.core.config import settings

    model = (
        settings.anthropic_model_primary
        if llm_provider == "anthropic"
        else settings.cerebra_ai_model_primary
    )
    resp = await chat_complete(
        system=SYSTEM_PROMPT,
        user=user_prompt,
        model=model,
        max_tokens=8000,
        provider=llm_provider,
        base_url=settings.cerebra_ai_base_url,
        ...
    )
    return resp.text
```

### 9. `log_llm_call` — custo CerebraAI

Em [`apps/agent/nodes/base.py`](apps/agent/nodes/base.py):

```python
if "haiku" in model.lower():
    cost = (input_tokens * 0.8 + output_tokens * 4.0) / 1_000_000
elif provider == "cerebra_ai":
    cost = 0.0  # self-hosted; custo de infra contabilizado separadamente
else:
    cost = (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000
```

### 10. Frontend — seletor de modelo no modal

Em [`apps/web/src/app/(dashboard)/repositories/page.tsx`](apps/web/src/app/(dashboard)/repositories/page.tsx):

- Novo state: `const [selectedProvider, setSelectedProvider] = useState<'anthropic' | 'cerebra_ai'>('anthropic')`
- Reset no `openAnalyzeModal`: `setSelectedProvider('anthropic')`
- Novo bloco de UI (radio cards), exemplo:

```
┌──────────────────────────────────┐
│  Model                           │
│  ○ Claude (Anthropic)  ← default │
│  ○ CerebraAI           ← novo    │
└──────────────────────────────────┘
```

- `triggerMutation.mutate` adiciona `llmProvider: selectedProvider`
- `triggerMutation` payload type adiciona `llmProvider: string`
- `analysesApi.trigger` em [`apps/web/src/lib/api.ts`](apps/web/src/lib/api.ts) aceita e envia `llm_provider`:

```typescript
trigger: (repoId, ref, type, changedFiles, llmProvider = 'anthropic') =>
  api.post('/api/v1/analyses', {
    repo_id: repoId,
    ref,
    analysis_type: type,
    llm_provider: llmProvider,
    ...(changedFiles?.length ? { changed_files: changedFiles } : {}),
  }).then(r => r.data)
```

### 11. `.env.local.example`

```env
# ─── CerebraAI (OpenAI-compatible / vLLM) ──────────────────────────────────
# Usado quando o usuário escolhe "CerebraAI" ao disparar uma análise na UI.
CEREBRA_AI_BASE_URL=http://52.86.35.131:8001/v1
CEREBRA_AI_API_KEY=                             # deixar vazio se sem auth
CEREBRA_AI_MODEL_PRIMARY=Qwen/Qwen3.5-35B-A3B-FP8
CEREBRA_AI_MODEL_TRIAGE=Qwen/Qwen3.5-35B-A3B-FP8
CEREBRA_AI_TEMPERATURE=0.4
CEREBRA_AI_TOP_P=0.9
CEREBRA_AI_TIMEOUT=300
```

---

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Qwen retorna markdown em vez de JSON puro | Strip de ` ``` ` já presente em `analyze_coverage`; manter em todos os parsers |
| fix_pr com `max_tokens=8000` lento no Qwen | `timeout=300s` configurável via env |
| `pre_triage` prefill incompatível | System prompt alternativo para caminho `cerebra_ai` |
| Dois arquivos de config | Ambos leem mesmo `.env.local` — vars declaradas uma vez |
| Nós sync vs adapter async | LangGraph já roda em event loop async; `await chat_complete(...)` sem problema |

---

## Ordem de implementação

1. DB migration + ORM model (`db-migration`, `orm-model`)
2. Config ambos os arquivos (`config-env`)
3. Adaptador `chat_completion.py` (`llm-adapter`)
4. API request + serviço (`api-request`)
5. Agent state (`agent-state`)
6. Nós do agente: `analyze_coverage` → `generate_suggestions` → `context_discovery` → `pre_triage` (`refactor-nodes`, `preflight-pretriage`)
7. Fix PR service (`refactor-fix-pr`)
8. `log_llm_call` (`log-cost`)
9. Frontend modal UI (`frontend-ui`)
10. `.env.local.example` (`docs-env`)
