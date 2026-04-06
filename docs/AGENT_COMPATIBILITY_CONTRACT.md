# Lumis Agent — Contrato de Compatibilidade para o Novo Serviço

> **Versão:** v1.0 — Abril 2026  
> **Audiência:** Equipe de desenvolvimento do `lumis-agent` TypeScript  
> **Objetivo:** Definir o que o novo serviço **deve garantir** para ser compatível com o ecossistema existente sem quebrar jobs antigos, o frontend, o banco de dados e os pipelines de RAG.

---

## 1. Princípio Fundamental

O Lumis nasceu com foco em **observabilidade de engenharia** — rastrear se o código está instrumentado corretamente para ser observado em produção. Isso se traduz nos pilares originais:

- **Traces** — propagação de contexto, spans em handlers, error recording
- **Metrics** — cobertura de latência/error rate, cardinality, instrumentation gates
- **Logs** — estrutura, correlação com trace, nível correto, sem debug em hot path

O novo sistema amplia o escopo (security, efficiency, compliance, testing), mas **não pode substituir nem rebatizar** esses pilares. A base de usuários espera ver "Logs", "Traces", "Metrics" na UI. Dados históricos usam esses valores.

---

## 2. Mapeamento de Pilares — Contrato de Compatibilidade

O novo agente usa pilares diferentes dos que existem no banco. Para coexistir com dados históricos e o frontend atual, o novo serviço deve **usar os valores canônicos abaixo** em toda saída de findings.

### 2.1 Pilares canônicos (valores válidos no campo `pillar`)

| Valor no campo `pillar` | Domínio | Quando usar |
|---|---|---|
| `traces` | Rastreamento distribuído (OTel spans, context propagation) | Handler sem span, goroutine sem contexto, async boundary quebrado |
| `logs` | Qualidade e estrutura de logs | Log não estruturado, debug em hot path, sem correlação trace_id |
| `metrics` | Instrumentação de métricas | Latência/error_rate ausentes, alta cardinalidade, sem SDK/agent |
| `iac` | Infrastructure-as-Code | Terraform/Helm/Bicep/K8s — hardcoded IDs, secrets, falta de tags |
| `pipeline` | CI/CD e pipeline de entrega | GitHub Actions, Dockerfile, deploy sem observabilidade |
| `security` | **NOVO** — vulnerabilidades de segurança | SQL injection, secrets expostos, OWASP, CVEs |
| `efficiency` | **NOVO** — custo e performance | N+1 queries, recursos excessivos, cache ausente |
| `compliance` | **NOVO** — conformidade e contratos | API contracts, migrations sem rollback, test coverage |

> **Regra:** Os valores `coverage`, `metrics` (como teste coverage), e qualquer valor não listado acima **não devem aparecer** no campo `pillar` dos findings retornados. Internamente o agente pode usar qualquer vocabulário — na saída final o `pillar` deve ser mapeado para os valores da tabela acima.

### 2.2 Mapeamento do vocabulário interno → canônico

| Conceito interno do TS agent | Pillar canônico na saída |
|---|---|
| `coverage` (observabilidade) | `traces` ou `logs` ou `metrics` (escolher o mais específico) |
| `coverage` (test coverage) | `compliance` |
| `efficiency` (query optimization, N+1) | `efficiency` |
| `efficiency` (resource limits, K8s) | `iac` |
| `security` | `security` |
| `compliance` (API contracts, migrations) | `compliance` |
| `compliance` (Dockerfile, CI/CD) | `pipeline` |
| IaC findings (μ-IaC agent) | `iac` |
| Logs sem estrutura / correlation | `logs` |
| Spans ausentes / context propagation | `traces` |
| Métricas ausentes / cardinality | `metrics` |

---

## 3. Campos Obrigatórios de Finding

Cada finding retornado deve conter exatamente estes campos no objeto de saída. Campos com `*` são novos (não existem no sistema atual mas devem ser incluídos para o Glue Layer persistir).

```typescript
interface Finding {
  // ── CAMPOS OBRIGATÓRIOS (existiam no sistema Python) ────────────────────
  pillar:       'traces' | 'logs' | 'metrics' | 'iac' | 'pipeline' | 'security' | 'efficiency' | 'compliance';
  severity:     'critical' | 'warning' | 'info';
  dimension:    string;              // Ver seção 4 — string livre agora
  title:        string;              // < 80 chars
  description:  string;             // O que falta e por que importa em produção
  filePath:     string | null;       // Path relativo ao repo root
  lineStart:    number | null;
  lineEnd:      number | null;
  suggestion:   string | null;       // Texto explicativo curto (1-3 frases)
  codeBefore:   string | null;       // Linhas exatas do arquivo original (extraídas do repoPath)
  codeAfter:    string | null;       // Versão corrigida, sintaticamente válida
  estimatedMonthlyCostImpact: number; // 0.0 se desconhecido

  // ── CAMPOS NOVOS (adicionados pelo multi-agent) ──────────────────────────
  confidence:       number;          // * Float 0.0–1.0 (>= 0.8 = alta, < 0.7 filtrar)
  sourceAgent:      string;          // * Ex: 'μ-node-typescript', 'D-security', 'D-observability'
  promptMode:       'fast' | 'standard' | 'deep' | 'verify'; // *
  verified:         boolean;         // * Passou pelo verify pass?
  reasoningExcerpt: string | null;   // * Chain-of-thought resumido (Deep/Verify only)

  // ── CAMPOS COMPUTADOS PELO GLUE LAYER (não retornar do agente) ──────────
  // isNew, crossrunStatus → calculados pelo Python após receber os findings
  // id → gerado pelo banco no INSERT
}
```

### 3.1 Regras críticas para `codeBefore` e `codeAfter`

O agente recebe `repoPath` e tem acesso aos arquivos em disco. A responsabilidade de preencher `codeBefore` é **do agente**, não do Glue Layer:

- `codeBefore` deve ser extraído das linhas reais do arquivo (`lineStart` a `lineEnd`)
- Nunca inventar código que não está no arquivo
- Para findings puramente aditivos (adicionar span onde não existe nenhum código), `codeBefore` pode ser `null`
- `codeAfter` deve ser sintaticamente válido para a linguagem do arquivo
- Para IaC (`.tf`, `.hcl`, `.yaml` K8s): `codeAfter` nunca pode conter imports de SDK de aplicação

### 3.2 Compatibilidade do campo `confidence`

O campo `confidence` **deve ser `number` (float 0.0–1.0)** na saída do novo agente. O banco armazenará como `FLOAT`. O Glue Layer converte para o formato esperado pelo frontend.

> O sistema Python antigo usava `confidence: "high"|"medium"|"low"` como string no JSONB. Para manter leitura de dados históricos funcionando, o frontend deve tratar ambos os formatos. O novo agente sempre retorna float.

**Mapeamento de referência:**

| Float | String equivalente (legado) | Ação do agente |
|---|---|---|
| `>= 0.80` | `"high"` | Reportar normalmente |
| `0.70 – 0.79` | `"medium"` | Reportar com cautela |
| `< 0.70` | `"low"` | **Não retornar** — filtrar antes da saída |

---

## 4. Dimensões — Valores Recomendados

A coluna `dimension` foi migrada de enum para `TEXT`. O campo aceita qualquer string. Os valores abaixo são recomendados para consistência com dados históricos e filtros futuros:

### 4.1 Dimensões de observabilidade (pilares traces/logs/metrics)

| Valor | Descrição |
|---|---|
| `coverage` | Ausência de instrumentação onde deveria existir |
| `snr` | Signal-to-noise ratio — log redundante, debug em hot path |
| `cost` | Custo de observabilidade (cardinality, retenção desnecessária) |
| `pipeline` | Propagação de contexto em pipelines assíncronos |
| `distributed_tracing` | Context propagation cross-service |
| `error_handling` | Erro sem span.RecordError() ou structured log |
| `async_patterns` | Goroutines, tasks, Promises sem propagação de contexto |
| `logging_structure` | Logs não estruturados, falta de correlação |
| `resource_attributes` | Atributos OTel ausentes (service.name, environment) |

### 4.2 Dimensões de segurança

| Valor | Descrição |
|---|---|
| `injection` | SQL, command, LDAP injection |
| `secret_exposure` | Credentials, API keys expostos no código |
| `dependency_vulnerability` | CVEs em dependências (npm, pip, go modules) |
| `authentication` | Falhas de auth/authz |
| `api_contract` | Validação de input ausente |

### 4.3 Dimensões de eficiência e compliance

| Valor | Descrição |
|---|---|
| `query_optimization` | N+1, full scans, índices ausentes |
| `migration_safety` | Migration sem rollback |
| `test_coverage` | Branches sem cobertura de teste |
| `dockerfile_best_practices` | Image sem pin, sem healthcheck |
| `architecture_coupling` | Acoplamento excessivo entre módulos |
| `resource_limits` | Pods sem limits/requests no K8s |
| `compliance` | (genérico — usar valor mais específico quando possível) |

### 4.4 Dimensões de IaC

| Valor | Descrição |
|---|---|
| `hardcoded_values` | IDs, VPCs, contas hardcoded |
| `missing_tags` | Tags organizacionais ausentes |
| `secret_in_config` | Secrets em values.yaml ou .tf |
| `missing_provider_constraints` | Versões de providers sem pin |
| `no_remote_backend` | Estado Terraform local |

---

## 5. Scores — Contrato de Saída

### 5.1 Campos obrigatórios no objeto `scores`

```typescript
interface Scores {
  global:     number;   // 0-100, média ponderada

  // ── Pilares originais (manter para compatibilidade) ──────────────────────
  traces:     number | null;   // null se não há arquivos de app analisados
  logs:       number | null;
  metrics:    number | null;

  // ── Pilares novos ────────────────────────────────────────────────────────
  security:   number | null;   // null se não há findings de security
  efficiency: number | null;   // null se não há findings de efficiency
  compliance: number | null;

  // ── Dimensões históricas (manter para não quebrar colunas do banco) ──────
  cost:       number | null;
  snr:        number | null;
  pipeline:   number | null;
}
```

### 5.2 Fórmula do score global (compatível com sistema atual)

O score global deve ser calculado como média ponderada dos pilares com instrumentation gate:

```
global = traces * 0.30 + logs * 0.35 + metrics * 0.35
       [+ security_penalty se score_security < 60]
```

**Instrumentation gate obrigatório:**
- Se nenhum SDK de instrumentação foi detectado nos arquivos (`opentelemetry`, `ddtrace`, `prometheus_client`, etc.) E não é repo IaC:
  - `metrics = 0`
  - `traces = 0`
  - Adicionar finding de pillar `metrics` com title `"No instrumentation detected"` e severity `"critical"`

**Penalidades por severidade (valores padrão):**

| Tipo | Critical | Warning | Info |
|---|---|---|---|
| Por dimension (custo, snr, pipeline, compliance) | −20 | −10 | −3 |
| Por pillar (metrics, logs, traces, iac) | −25 | −12 | −5 |

Score mínimo por pillar: 0 (nunca negativo).

### 5.3 Mapeamento para colunas do banco

O Glue Layer persiste os scores nas seguintes colunas de `analysis_results`:

| Campo de `scores` retornado | Coluna em `analysis_results` |
|---|---|
| `scores.global` | `score_global` |
| `scores.metrics` | `score_metrics` |
| `scores.logs` | `score_logs` |
| `scores.traces` | `score_traces` |
| `scores.cost` | `score_cost` |
| `scores.snr` | `score_snr` |
| `scores.pipeline` | `score_pipeline` |
| `scores.compliance` | `score_compliance` |
| `scores.coverage` | `score_coverage` (nova coluna) |
| `scores.efficiency` | `score_efficiency` (nova coluna) |
| `scores.security` | `score_security` (nova coluna) |

---

## 6. Base de Conhecimento (RAG) — Contrato de Acesso

### 6.1 Regras de acesso ao banco

O agente TS acessa diretamente **apenas** a tabela `knowledge_chunks`. Todas as outras tabelas são responsabilidade do Glue Layer Python.

```sql
-- Apenas estas operações são permitidas ao agente TS:
SELECT ... FROM knowledge_chunks WHERE ...
INSERT INTO knowledge_chunks ...
-- Proibido:
UPDATE/DELETE em analysis_jobs, analysis_results, findings, finding_feedback, repositories
```

### 6.2 `source_type` — valores válidos para leitura e escrita

O agente pode **ler** chunks de qualquer `source_type`. Ao **escrever** (feedback ingestion, analysis extractor), deve usar apenas os valores abaixo:

| `source_type` | Quem escreve | Quando |
|---|---|---|
| `otel_docs` | Celery task `ingest_global_docs` | Semanal — docs OTel SDK |
| `dd_docs` | Celery task `ingest_global_docs` | Semanal — docs Datadog |
| `tenant_standards` | API endpoint de upload | Quando tenant faz upload |
| `analysis_history` | **Glue Layer Python** (não o agente) | Após análise concluída |
| `cross_repo_pattern` | **Glue Layer Python** (não o agente) | Semanal via Celery Beat |
| `feedback_derived` | **Agente TS** via `feedbackIngestion` | Quando `feedbackHistory` presente |
| `agent_pattern` | **Agente TS** via `feedbackIngestion` | Findings com confidence ≥ 0.8 |
| `verified_pattern` | **Agente TS** via verify pass | Findings confirmados pelo verify |
| `repo_context` | Celery task `scan_repo_context` | Context discovery |
| `security_docs` | Celery task `ingest_global_docs` | OWASP, CWE |
| `language_docs` | Celery task `ingest_global_docs` | Best practices por linguagem |
| `architecture_docs` | Celery task `ingest_global_docs` | Clean Architecture, DDD |
| `devops_docs` | Celery task `ingest_global_docs` | Docker, Terraform, K8s |

> **Regra de não-duplicação:** O agente TS **não deve escrever** `source_type='analysis_history'`. O Glue Layer Python faz isso via `ingest_analysis_history` Celery task. Escrever dos dois lados gera duplicação.

### 6.3 `pillar` e `language` nos chunks — valores aceitos

A tabela `knowledge_chunks` usa `pillar` e `language` como filtros de retrieval:

**Pillar** (coluna `pillar` em `knowledge_chunks`):
```
traces | logs | metrics | iac | pipeline | security | efficiency | compliance
```

**Language** (coluna `language` em `knowledge_chunks`):
```
go | python | java | node | terraform | helm | typescript | javascript | rust | java | cpp
```

> Atenção: a convenção é **minúsculo** nos chunks. O agente recebe `repoContext.languages` do Glue Layer já normalizado para minúsculo.

### 6.4 `confidence_score` em chunks escritos pelo agente

| Origem do chunk | `confidence_score` |
|---|---|
| Chunk gerado de finding com `confidence >= 0.9` | `1.0` |
| Chunk gerado de finding com `confidence 0.8–0.89` | `0.9` |
| Feedback com `thumbs_up` acumulado (≥3) | `0.85 + (count * 0.02)` capped em 1.0 |
| Feedback com `thumbs_down` (false positive) | `0.3` |

---

## 7. Padrões Semânticos do Projeto Original

Esta seção define as convenções que o sistema Python atual aplica e que **devem ser preservadas** pelo novo agente para manter coerência de findings entre versões.

### 7.1 O que NUNCA reportar (negative examples canônicos)

Os patterns abaixo estão hardcoded no sistema Python como falsos positivos conhecidos. O novo agente deve respeitar as mesmas exclusões:

```
NÃO reportar:
✗ Funções utilitárias puras sem I/O (formatters, validators, math helpers)
✗ errors.Is(err, ErrNotFound) / errors.As — tratamento intencional de not-found
✗ Log de 404/401 em nível DEBUG — redução intencional de ruído
✗ Endpoints de health check (/healthz, /readyz, /ping, /health) — não devem ter traces
✗ Arquivos de teste (_test.go, test_*.py, *.spec.ts, *.test.ts) — não analisar
✗ Import statements, declarações de variáveis, definições de struct — não são execution paths
✗ Funções init, setup, teardown, close, shutdown — lifecycle, não business logic
✗ Sugestões de SDK de aplicação em arquivos .tf, .hcl, .yaml K8s — IaC constraint
```

### 7.2 Padrões de instrumentação detectados como "presente"

O sistema verifica a presença destes patterns para determinar se o código já tem instrumentação:

**App SDK patterns (detectam SDK no código-fonte):**
```regex
opentelemetry | ddtrace | dd-trace | dd\.tracer | datadog\.tracer
opentracing | opencensus | openmetrics
prometheus_client | prom-client | prom\.NewCounter
statsd\.
go\.opentelemetry\.io | gopkg\.in/DataDog/dd-trace-go
io\.opentelemetry | io\.opentracing
@opentelemetry/ | datadog-lambda
micrometer | otel\.trace
tracer\.start_as_current_span | tracer\.startActiveSpan | startActiveSpan
```

**Infra agent patterns (detectam agente no compose/config):**
```regex
datadog[/_-]agent | datadog/agent:
otel[/_-]collector | opentelemetry[/_-]collector | otelcol
prometheus[/_-]operator | kube[_-]prometheus
node[_-]exporter | alertmanager
grafana[/_-]agent | victoriametrics | thanos
fluent[/_-]bit | fluentd
```

**Instrumentation gate:**
- Se nenhum dos dois grupos foi detectado E não é repo IaC → `score_metrics = 0`, `score_traces = 0`
- Se apenas infra agent (sem app SDK) → `score_traces = 0` (traces requerem SDK no app)

### 7.3 Padrões de detecção de span (presença de instrumentação por arquivo)

```regex
tracer\.start | span\s*= | StartSpan | start_as_current_span
startActiveSpan | opentelemetry\.trace | ddtrace\.tracer
dd\.trace | tracer\.trace\(
```

### 7.4 Checklists por linguagem — hints obrigatórios

O agente deve verificar os seguintes padrões específicos por linguagem:

#### Go
```
→ context.Context passado mas NÃO propagado para todos os callees (lost trace context)
→ go func() lançando goroutines SEM propagar context (orphan goroutine)
→ if err != nil { return err } em critical paths SEM span.RecordError()
→ HTTP handler que lê r.Context() mas nunca chama tracer.Start(ctx, ...)
```

#### Python
```
→ except Exception: / bare except: SEM span.record_exception() ou logger.error(exc_info=True)
→ asyncio.create_task() SEM propagar contexto OTel (context.copy_context())
→ Celery task @task SEM extrair W3C traceparent dos headers
→ FastAPI/Flask endpoint handler SEM tracer.start_as_current_span()
```

#### TypeScript / JavaScript
```
→ .catch(err => ...) SEM activeSpan.recordException(err)
→ setTimeout / setInterval callbacks SEM context.with()
→ new Promise() executor SEM propagar contexto OTel
→ Express/Fastify route handler SEM atributos de span (http.method, http.route)
→ async function com await SEM propagar active span
→ NestJS @Controller SEM @Span() decorator ou tracer.startActiveSpan()
```

#### Java
```
→ @Async method SEM MDC propagation (trace context perdido no thread pool)
→ CompletableFuture.supplyAsync() SEM passar o Context atual
→ Spring @Service fazendo DB calls SEM active span
```

#### Terraform / HCL
```
→ Resource IDs, VPC IDs, subnet IDs, account IDs hardcoded
→ Sem isolamento de ambiente (mesmos IDs em dev/staging/prod)
→ Secrets/API keys hardcoded em .tf
→ required_providers sem version constraints
→ Sem remote backend configurado
→ Sem validation blocks em inputs críticos
→ Tags organizacionais ausentes (env, team, project)
```

#### Helm / Kubernetes YAML
```
→ Image tags hardcoded (usar .Values.image.tag)
→ Resource limits não definidos
→ Sem liveness/readiness probes
→ Secrets em values.yaml (usar external-secrets ou sealed-secrets)
```

### 7.5 Constraint de IaC — regra não-negociável

Quando `repoContext.repoType === 'infra'` ou arquivos `.tf`/`.hcl` são detectados:

```
NUNCA sugerir:
✗ Python: from opentelemetry import trace
✗ Node.js / TypeScript: import * from '@opentelemetry/...'
✗ dd-trace, ddtrace, datadog-lambda
✗ Qualquer import de runtime de aplicação em arquivos de infra

SEMPRE sugerir:
✓ Terraform: variable, locals, data sources, terraform.workspace
✓ Helm: .Values.* references
✓ K8s: resources.limits, probes, networkPolicies
✓ AWS: SSM Parameter Store, Secrets Manager references
```

### 7.6 Framework detection — contexto adicional para o LLM

O agente deve detectar e incluir no contexto de análise:

| Linguagem | Frameworks | Pattern de detecção |
|---|---|---|
| Python | FastAPI | `from fastapi` / `import fastapi` |
| Python | Flask | `from flask` / `import flask` |
| Python | Celery | `from celery` / `import celery` |
| Go | Gin | `"github.com/gin-gonic/gin"` |
| Go | net/http | `"net/http"` |
| TypeScript | Express | `from 'express'` / `require('express')` |
| TypeScript | NestJS | `from '@nestjs` |
| Java | Spring | `import org.springframework` |

---

## 8. Estrutura de Análise — Mandatory Reasoning Framework

O agente deve, internamente, responder estas 4 perguntas antes de reportar qualquer finding:

```
Q1. Esse código path lida com dinheiro, dados de usuário ou SLA crítico?
Q2. Onde o trace context pode ser silenciosamente descartado?
    (async boundaries, goroutines, thread pools, Promise chains)
Q3. Quais error paths são completamente cegos?
    (sem span, sem log estruturado, sem métrica)
Q4. Há ruído alto-cardinalidade ou instrumentação redundante?

→ Reportar APENAS findings que respondem Q1, Q2, ou Q3 afirmativamente
  E Q4 negativamente.
```

---

## 9. `lumis-ignore` — Suporte Obrigatório

O sistema atual suporta supressão de findings via comentário inline:

```go
// lumis-ignore
if err != nil { return err }   // finding nesta linha é suprimido
```

O agente deve:
1. Durante `preTriage`, escanear arquivos por comentários `// lumis-ignore`, `# lumis-ignore`, `/* lumis-ignore */`
2. Armazenar as supressões como `{ filePath: string, line: number }[]`
3. Após deduplicação, filtrar qualquer finding cujo `(filePath, lineStart)` coincida com uma supressão
4. Retornar a lista de supressões aplicadas para fins de auditoria (campo `suppressions` no `AnalysisResult`)

---

## 10. Cross-Run Diff — Responsabilidade do Glue Layer

O agente TS **não calcula** `is_new` / `crossrun_status`. Essa responsabilidade fica no Glue Layer Python, que:

1. Recebe os findings do agente TS
2. Carrega os findings do job anterior para o mesmo repo (via DB)
3. Compara fingerprints: `"{pillar}:{filePath}:{lineStart}:{title[:50]}"`
4. Seta `isNew: true` e `crossrunStatus: "new"` para findings sem match
5. Seta `crossrunStatus: "persisting"` para findings com match

O agente deve **não incluir** `isNew` ou `crossrunStatus` nos findings retornados. Esses campos serão adicionados pelo Glue Layer antes da persistência.

O `previousFindings` passado como input serve **apenas para calibração do RAG e do verify pass** — não para dedup de output.

---

## 11. Normalização de Entrada — Responsabilidade do Glue Layer

Antes de chamar o agente, o Glue Layer Python normaliza:

| Campo no DB | Transformação | Valor enviado ao agente |
|---|---|---|
| `repo.repo_type = "app"` | Mapeamento | `repoContext.repoType = "backend"` |
| `repo.repo_type = "iac"` | Mapeamento | `repoContext.repoType = "infra"` |
| `repo.language = ["Go", "Python"]` | `.map(l => l.toLowerCase())` | `repoContext.languages = ["go", "python"]` |
| `repo.observability_backend = "grafana"` | Pass-through | `repoContext.observabilityBackend = "grafana"` |
| `job.changed_files.files` | Pass-through | `changedFiles: [...]` |
| `repo.analysis_config` | Pass-through | Permite `disabledAgents`, `preferredAgents` |

---

## 12. Contrato de Saída Completo (`AnalysisResult`)

```typescript
interface AnalysisResult {
  // ── OBRIGATÓRIOS ──────────────────────────────────────────────────────────
  findings:      Finding[];          // Deduplicados, ordenados critical→warning→info
  scores:        Scores;             // Ver seção 5
  suggestions:   Suggestion[];       // Code patches, vinculados aos findings
  tokenUsage:    TokenUsage;
  agentBreakdown: Record<string, AgentStats>;

  // ── OPCIONAIS ──────────────────────────────────────────────────────────────
  contextSummary?: string;           // Apenas para analysisType = 'context'
  suppressions?:   Suppression[];    // Findings suprimidos por lumis-ignore
  detectedLanguages?: string[];      // Linguagens detectadas no pre_triage
  activeAgents?:   string[];         // Agentes ativados pelo dispatcher
}

interface Suggestion {
  findingTitle: string;              // Deve coincidir com finding.title
  findingFilePath: string;           // OBRIGATÓRIO — evitar merge ambíguo por título
  filePath: string;
  codeBefore: string | null;
  codeAfter: string;
  explanation: string;
}

interface TokenUsage {
  promptTokens:    number;
  completionTokens: number;
  totalTokens:     number;
  // Nota: cost_usd não é calculado (Qwen self-hosted) — Glue Layer zera este campo
}
```

> `Suggestion.findingFilePath` é obrigatório (não presente no TS doc original) para evitar merge ambíguo quando dois findings têm o mesmo título em arquivos diferentes.

---

## 13. Progress Events — Eventos SSE Esperados pelo Frontend

O agente TS é síncrono. O Glue Layer publica os seguintes eventos no Redis para o SSE do frontend:

| Stage | % | Momento |
|---|---|---|
| `cloning` | 5 | Início do git clone |
| `cloning` | 10 | Clone concluído |
| `triaging` | 15 | Início pre_triage |
| `triaging` | 20 | pre_triage concluído |
| `analyzing` | 25 | Chamada ao agente TS iniciada |
| `analyzing` | 50 | (opcional) Heartbeat se agente demorar > 60s |
| `scoring` | 75 | Agente retornou — computando scores e crossrun |
| `posting` | 90 | Iniciando persistência no banco |
| `done` | 100 | Análise concluída |

Canal Redis: `t:{tenantId}:analysis:{jobId}:progress`

Formato do evento:
```json
{
  "stage": "analyzing",
  "progress_pct": 50,
  "message": "Analyzing with 6 specialized agents...",
  "timestamp": "2026-04-05T14:00:00.000Z"
}
```

---

## 14. Resumo — Checklist de Compatibilidade

Antes de considerar o novo serviço compatível, verificar:

- [ ] `pillar` usa apenas os 8 valores canônicos (seção 2)
- [ ] `confidence` é `number` (float 0.0–1.0), nunca string
- [ ] `dimension` é string livre (coluna DB mudou de enum para TEXT)
- [ ] `codeBefore` é extraído das linhas reais do arquivo (não inventado)
- [ ] `Suggestion` inclui `findingFilePath` para merge não-ambíguo
- [ ] `scores` inclui `traces`, `logs`, `metrics` (pilares históricos) além dos novos
- [ ] Instrumentation gate zera `metrics` e `traces` quando sem SDK detectado
- [ ] `lumis-ignore` é respeitado antes de retornar findings
- [ ] Agente TS **não escreve** `source_type='analysis_history'` no knowledge_chunks
- [ ] `repoContext.languages` é recebido em minúsculo (normalizado pelo Glue Layer)
- [ ] Negative examples da seção 7.1 nunca aparecem como findings
- [ ] IaC constraint da seção 7.5 é respeitada para arquivos .tf/.hcl/.yaml
- [ ] `isNew` e `crossrunStatus` **não são** campos retornados (computados pelo Glue Layer)
- [ ] Não há `pillar='coverage'` na saída (é um pilar interno, não canônico)
- [ ] `cost_usd` não é calculado (Qwen self-hosted) — campo omitido na saída
