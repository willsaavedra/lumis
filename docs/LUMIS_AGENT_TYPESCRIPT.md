# Lumis Agent — Motor de Inteligência (LangGraph + TypeScript)

> **Versão:** v7 — Abril 2026  
> **Runtime:** Node.js + TypeScript  
> **Orquestração:** LangGraph.js (StateGraph)  
> **Modelo:** Qwen3.5-35B-A3B-FP8 via vLLM (OpenAI-compatible)  
> **Banco Semântico:** pgvector (PostgreSQL)  
> **Escopo:** Apenas inteligência. Chamado via API por outro serviço.

---

## 1. Escopo e Responsabilidades

### O que este serviço FAZ

- Receber um payload de análise (código, metadata do repo, changed files)
- Executar o grafo LangGraph com agentes especializados
- Consultar e alimentar a base de conhecimento (pgvector)
- Retornar findings, scores e sugestões como resposta

### O que este serviço NÃO faz

- Não tem rotas REST (quem expõe a API é outro serviço)
- Não gerencia jobs, filas ou workers (o caller gerencia)
- Não faz billing, auth, ou multi-tenant logic
- Não faz git clone (recebe o código já clonado ou os arquivos como input)
- Não comenta em PRs (retorna os dados, o caller posta)

### Como é chamado

```typescript
// O serviço que chama (API/Worker existente) faz:
import { runAnalysis } from '@lumis/agent';

const result = await runAnalysis({
  jobId: 'uuid-do-job',
  tenantId: 'uuid-do-tenant',
  repoId: 'uuid-do-repo',
  repoPath: '/tmp/lumis-clone-xyz',  // já clonado pelo caller
  changedFiles: ['src/controllers/user.ts', 'migrations/001.sql'],
  analysisType: 'full',              // quick | full | repository | context
  repoContext: {
    languages: ['typescript', 'sql'],
    repoType: 'backend',
    observabilityBackend: 'datadog',
    contextSummary: '...',
    obsMetadata: { /* ... */ },
  },
});

// result: { findings, scores, suggestions, tokenUsage, agentBreakdown }
```

---

## 1.1 Exemplo Completo de Payload de Entrada

```jsonc
// POST para o serviço ou chamada direta: runAnalysis(payload)
{
  "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "tenantId": "t-00000001-aaaa-bbbb-cccc-dddddddddddd",
  "repoId": "r-11111111-2222-3333-4444-555555555555",
  
  // Path do clone já feito pelo caller (o agente só lê arquivos daqui)
  "repoPath": "/tmp/lumis-clone-a1b2c3d4",
  
  // Arquivos que mudaram nesta PR/push (obrigatório para quick, opcional para full)
  "changedFiles": [
    "src/controllers/userController.ts",
    "src/services/authService.ts",
    "src/models/user.ts",
    "src/repositories/userRepository.ts",
    "migrations/20260401_add_user_preferences.sql",
    "Dockerfile",
    "src/__tests__/auth.test.ts",
    "package.json"
  ],
  
  // Tipo de análise
  "analysisType": "full",  // "quick" | "full" | "repository" | "context"
  
  // Contexto do repositório (vem da tabela repositories)
  "repoContext": {
    "languages": ["typescript", "sql"],
    "repoType": "backend",
    "observabilityBackend": "datadog",
    "appSubtype": "api-rest",
    "iacProvider": "docker",
    "instrumentation": "opentelemetry",
    "obsMetadata": {
      "ddService": "user-service",
      "ddEnv": "production",
      "tracingEnabled": true,
      "customMetrics": ["user.signup.count", "auth.failure.rate"]
    },
    "contextSummary": "API REST em TypeScript/Express para gestão de usuários. Usa PostgreSQL com TypeORM. Instrumentada com OpenTelemetry e Datadog APM. Deploy via Docker no ECS."
  },
  
  // Findings da análise anterior (para diff crossrun) — opcional
  "previousFindings": [
    {
      "title": "Missing error handling in auth middleware",
      "pillar": "coverage",
      "severity": "warning",
      "filePath": "src/middleware/auth.ts",
      "lineStart": 45
    },
    {
      "title": "N+1 query in user listing",
      "pillar": "efficiency",
      "severity": "critical",
      "filePath": "src/repositories/userRepository.ts",
      "lineStart": 23
    }
  ],
  
  // Feedback dos devs sobre findings anteriores (para calibração) — opcional
  "feedbackHistory": [
    {
      "findingTitle": "Missing error handling in auth middleware",
      "pillar": "coverage",
      "signal": "thumbs_up",
      "note": "Corrigido na última sprint"
    },
    {
      "findingTitle": "Console.log in production code",
      "pillar": "compliance",
      "signal": "thumbs_down",
      "note": "É debug intencional, não remover"
    },
    {
      "findingTitle": "N+1 query in user listing",
      "pillar": "efficiency",
      "signal": "applied",
      "note": null
    }
  ]
}
```

---

## 1.2 Exemplo Completo de Payload de Resposta

```jsonc
// Retorno de runAnalysis() → AnalysisResult
{
  // ═══ FINDINGS ═══
  // Lista completa de issues encontrados, já deduplicados e verificados
  "findings": [
    {
      "severity": "critical",
      "title": "SQL injection vulnerability in user search",
      "description": "O parâmetro 'query' é concatenado diretamente na string SQL sem sanitização em userRepository.ts:34. Um atacante pode injetar SQL arbitrário via endpoint GET /users/search?q=...",
      "filePath": "src/repositories/userRepository.ts",
      "lineStart": 34,
      "lineEnd": 38,
      "suggestion": "Usar parameterized queries do TypeORM: .where('user.name LIKE :query', { query: `%${query}%` }) ao invés de template literals.",
      "pillar": "security",
      "dimension": "injection",
      "confidence": 0.95,
      "sourceAgent": "D-security",
      "promptMode": "deep",
      "verified": true,          // Passou pelo verify pass
      "reasoningExcerpt": "O input do usuário flui diretamente para a query SQL sem sanitização. O endpoint é público (não requer auth). Classificado como critical porque permite exfiltração de dados.",
      "estimatedMonthlyCostImpact": null
    },
    {
      "severity": "critical",
      "title": "N+1 query in user listing endpoint",
      "description": "O método findAllWithPreferences() executa uma query separada para cada usuário ao carregar preferences. Com 1000 usuários, são 1001 queries ao banco.",
      "filePath": "src/repositories/userRepository.ts",
      "lineStart": 52,
      "lineEnd": 67,
      "suggestion": "Adicionar eager loading: this.userRepo.find({ relations: ['preferences'] }) ou usar QueryBuilder com leftJoinAndSelect.",
      "pillar": "efficiency",
      "dimension": "query_optimization",
      "confidence": 0.92,
      "sourceAgent": "D-dba",
      "promptMode": "deep",
      "verified": false,
      "reasoningExcerpt": "Detectado padrão de loop com query individual. O call graph confirma que findAllWithPreferences é chamado pelo endpoint GET /users que retorna listas paginadas.",
      "estimatedMonthlyCostImpact": 45.00
    },
    {
      "severity": "warning",
      "title": "Missing distributed tracing context propagation",
      "description": "O authService.ts faz chamada HTTP para o identity-provider mas não propaga o trace context (W3C traceparent header). Traces ficam quebrados no Datadog APM.",
      "filePath": "src/services/authService.ts",
      "lineStart": 78,
      "lineEnd": 85,
      "suggestion": "Usar o fetch instrumentado do @opentelemetry/instrumentation-fetch ou adicionar manualmente o header traceparent na chamada HTTP.",
      "pillar": "coverage",
      "dimension": "distributed_tracing",
      "confidence": 0.88,
      "sourceAgent": "D-observability",
      "promptMode": "deep",
      "verified": false,
      "reasoningExcerpt": "A instrumentação OTel está configurada mas o HTTP client usado (node-fetch) não está na lista de auto-instrumentations. O header traceparent não é propagado manualmente.",
      "estimatedMonthlyCostImpact": null
    },
    {
      "severity": "warning",
      "title": "Unhandled promise rejection in error middleware",
      "description": "O catch block em errorHandler.ts:12 não trata o caso onde logger.error() pode rejeitar (ex: conexão com log aggregator caiu). Isso causa unhandled promise rejection e crash do processo.",
      "filePath": "src/middleware/errorHandler.ts",
      "lineStart": 12,
      "lineEnd": 18,
      "suggestion": "Envolver logger.error() em try/catch ou usar .catch(() => {}) para evitar crash por falha no logging.",
      "pillar": "compliance",
      "dimension": "error_handling",
      "confidence": 0.82,
      "sourceAgent": "μ-node-typescript",
      "promptMode": "standard",
      "verified": false,
      "reasoningExcerpt": null,
      "estimatedMonthlyCostImpact": null
    },
    {
      "severity": "warning",
      "title": "Migration is not reversible",
      "description": "A migration 20260401_add_user_preferences.sql usa ALTER TABLE ADD COLUMN mas não tem um bloco DOWN/rollback. Em caso de deploy com problema, não é possível reverter automaticamente.",
      "filePath": "migrations/20260401_add_user_preferences.sql",
      "lineStart": 1,
      "lineEnd": 15,
      "suggestion": "Adicionar seção de rollback: ALTER TABLE users DROP COLUMN IF EXISTS preferences;",
      "pillar": "compliance",
      "dimension": "migration_safety",
      "confidence": 0.90,
      "sourceAgent": "D-dba",
      "promptMode": "deep",
      "verified": false,
      "reasoningExcerpt": null,
      "estimatedMonthlyCostImpact": null
    },
    {
      "severity": "info",
      "title": "Test coverage gap: authService.validateToken",
      "description": "O método validateToken() em authService.ts tem 3 branches (token válido, expirado, malformed) mas o test file só cobre o caso de token válido.",
      "filePath": "src/__tests__/auth.test.ts",
      "lineStart": 1,
      "lineEnd": 45,
      "suggestion": "Adicionar test cases para token expirado e token malformed. Considerar usar test.each() para parametrizar.",
      "pillar": "metrics",
      "dimension": "test_coverage",
      "confidence": 0.78,
      "sourceAgent": "D-testing",
      "promptMode": "standard",
      "verified": false,
      "reasoningExcerpt": null,
      "estimatedMonthlyCostImpact": null
    },
    {
      "severity": "info",
      "title": "Dockerfile uses node:latest tag",
      "description": "O Dockerfile usa FROM node:latest ao invés de uma versão pinada. Builds podem quebrar silenciosamente quando a imagem base atualiza.",
      "filePath": "Dockerfile",
      "lineStart": 1,
      "lineEnd": 1,
      "suggestion": "Pinar a versão: FROM node:22.12-alpine3.21",
      "pillar": "compliance",
      "dimension": "dockerfile_best_practices",
      "confidence": 0.95,
      "sourceAgent": "D-devops",
      "promptMode": "standard",
      "verified": false,
      "reasoningExcerpt": null,
      "estimatedMonthlyCostImpact": null
    }
  ],

  // ═══ SCORES ═══
  // Nota de 0-100 por pilar de qualidade
  "scores": {
    "global": 62,
    "coverage": 58,       // Tracing parcial, logs sem correlation
    "metrics": 45,        // Gaps de teste
    "efficiency": 40,     // N+1 query critical
    "compliance": 72,     // Migration sem rollback, Dockerfile sem pin
    "security": 35        // SQL injection critical
  },

  // ═══ SUGGESTIONS ═══
  // Code patches para os findings mais críticos
  "suggestions": [
    {
      "findingTitle": "SQL injection vulnerability in user search",
      "filePath": "src/repositories/userRepository.ts",
      "codeBefore": "const users = await this.userRepo.query(\n  `SELECT * FROM users WHERE name LIKE '%${query}%'`\n);",
      "codeAfter": "const users = await this.userRepo\n  .createQueryBuilder('user')\n  .where('user.name LIKE :query', { query: `%${query}%` })\n  .getMany();",
      "explanation": "Substituir template literal por parameterized query do TypeORM. O QueryBuilder escapa automaticamente o input do usuário, prevenindo SQL injection."
    },
    {
      "findingTitle": "N+1 query in user listing endpoint",
      "filePath": "src/repositories/userRepository.ts",
      "codeBefore": "async findAllWithPreferences(): Promise<User[]> {\n  const users = await this.userRepo.find();\n  for (const user of users) {\n    user.preferences = await this.prefRepo.findBy({ userId: user.id });\n  }\n  return users;\n}",
      "codeAfter": "async findAllWithPreferences(): Promise<User[]> {\n  return this.userRepo.find({\n    relations: ['preferences'],\n  });\n}",
      "explanation": "Usar eager loading do TypeORM para carregar preferences em uma única query com JOIN ao invés de N queries individuais."
    }
  ],

  // ═══ TOKEN USAGE ═══
  // Consumo total de tokens do Qwen nesta análise
  "tokenUsage": {
    "promptTokens": 45230,
    "completionTokens": 18750,
    "totalTokens": 63980
  },

  // ═══ AGENT BREAKDOWN ═══
  // Detalhamento por agente: quantas chamadas, tokens, findings
  "agentBreakdown": {
    "dispatcher": {
      "mode": "fast",
      "calls": 1,
      "promptTokens": 820,
      "completionTokens": 350,
      "findingsCount": 0
    },
    "μ-node-typescript": {
      "mode": "standard",
      "calls": 2,
      "promptTokens": 8400,
      "completionTokens": 3200,
      "findingsCount": 1
    },
    "D-security": {
      "mode": "deep",
      "calls": 2,
      "promptTokens": 9500,
      "completionTokens": 4100,
      "findingsCount": 1
    },
    "D-dba": {
      "mode": "deep",
      "calls": 1,
      "promptTokens": 6200,
      "completionTokens": 2800,
      "findingsCount": 2
    },
    "D-observability": {
      "mode": "deep",
      "calls": 3,
      "promptTokens": 12000,
      "completionTokens": 4500,
      "findingsCount": 1
    },
    "D-testing": {
      "mode": "standard",
      "calls": 1,
      "promptTokens": 3800,
      "completionTokens": 1400,
      "findingsCount": 1
    },
    "D-devops": {
      "mode": "standard",
      "calls": 1,
      "promptTokens": 2100,
      "completionTokens": 900,
      "findingsCount": 1
    },
    "verify": {
      "mode": "verify",
      "calls": 1,
      "promptTokens": 2410,
      "completionTokens": 1500,
      "findingsCount": 0
    }
  }
}
```

### Notas sobre a resposta

- **`findings`** já vem deduplicado e ordenado por severidade (critical → warning → info)
- **`verified: true`** indica que o finding passou pela segunda passada do agente Verify (só findings critical e de segurança passam)
- **`sourceAgent`** mostra qual agente gerou: prefixo `μ-` = micro agente de linguagem, `D-` = agente de domínio
- **`reasoningExcerpt`** é um resumo do campo `reasoning` do Qwen (chain-of-thought). Presente nos modos Deep e Verify, null em Fast/Standard
- **`confidence`** é 0-1, onde ≥0.8 é alta confiança. Findings com confidence < 0.7 podem ser candidatos a verificação adicional
- **`agentBreakdown`** permite ao caller rastrear custo e performance por agente, e identificar quais agentes estão sendo mais úteis
- **`scores`** são de 0-100. O `global` é uma média ponderada dos pilares (security tem peso maior)

---

## 2. Credenciais e Endpoints

### 2.1 Qwen 3.5 via vLLM (staging)

```env
QWEN_API_URL=http://52.86.35.131:8001
QWEN_MODEL=Qwen/Qwen3.5-35B-A3B-FP8
QWEN_TIMEOUT=60000
QWEN_MAX_RETRIES=3
```

**Request (OpenAI-compatible):**

```json
{
  "model": "Qwen/Qwen3.5-35B-A3B-FP8",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "stream": false,
  "temperature": 0.4,
  "top_p": 0.9,
  "max_tokens": 1500
}
```

**Response — campo `reasoning` separado do `content`:**

```json
{
  "choices": [{
    "message": {
      "content": "resposta final (JSON dos findings)",
      "reasoning": "chain-of-thought automático (separado)"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 587
  }
}
```

### 2.2 PostgreSQL (pgvector)

```env
DATABASE_URL=postgresql://sre:local_only@192.168.15.14:5432/lumis
```

> O agente acessa o banco **apenas para knowledge_chunks** (leitura e escrita de RAG). Todas as outras tabelas (jobs, results, findings, tenants) são responsabilidade do serviço que chama.

---

## 3. Arquitetura de Agentes (3 Níveis)

### 3.1 Nível 1 — Orquestração

| Agente | Modo | Responsabilidade |
|--------|------|------------------|
| Dispatcher | Fast | Analisa input, decide quais agentes ativar baseado em linguagens e artefatos |
| Contexto & Triagem | Fast | Classifica arquivos por tipo e linguagem |
| RAG Retriever | Fast | Busca e re-ranking de knowledge_chunks no pgvector |
| Scoring | Fast | Agrega scores por pilar e global |
| Sugestões | Standard | Gera code patches priorizados |

### 3.2 Nível 2 — Domínio (cross-cutting)

| Agente | Modo | Pilar |
|--------|------|-------|
| Segurança | Deep + Verify | security |
| DBA / Banco | Deep | efficiency |
| API & Contratos | Standard | compliance |
| Testes | Standard | metrics |
| Observabilidade | Deep | coverage |
| Performance | Deep | efficiency |
| Arquitetura | Deep | compliance |
| Dependências | Fast | security |
| DevOps / Infra | Standard | compliance |
| Logs & Observ. | Standard | coverage |

### 3.3 Nível 3 — Micro Agentes (por linguagem)

| Agente | Modo | Ativado quando |
|--------|------|----------------|
| μ Node.js / TypeScript | Standard→Deep | languages inclui 'typescript' ou 'javascript' |
| μ Go | Standard→Deep | languages inclui 'go' |
| μ Python | Standard→Deep | languages inclui 'python' |
| μ Rust | Deep | languages inclui 'rust' |
| μ Java / Kotlin | Standard→Deep | languages inclui 'java' ou 'kotlin' |
| μ C / C++ | Deep | languages inclui 'c' ou 'cpp' |
| μ React / Frontend | Standard | detecta React/Vue/Angular |
| μ IaC / Terraform | Standard | detecta .tf, Dockerfile, .yaml k8s |

---

## 4. Modos de Prompt

Modelo único (Qwen 3.5). Diferenciação por temperatura e estratégia:

| Modo | Temperature | top_p | max_tokens | Reasoning |
|------|-------------|-------|------------|-----------|
| **Fast** | 0.1 | 0.9 | 1024 | Ignorado |
| **Standard** | 0.3 | 0.9 | 2048 | Armazenado |
| **Deep** | 0.4 | 0.9 | 4096 | Audit trail |
| **Verify** | 0.2 | 0.85 | 1024 | Confirmação |

---

## 5. Grafo LangGraph — Fluxo

### 5.1 Fluxo principal (full)

```
INPUT (payload do caller)
  ↓
pre_triage [Fast]
  ↓ (analysis_type == "context" → context_discovery → RETURN)
dispatcher [Fast]
  ↓ (paralelo)
  ┬─ retrieve_context [Fast] (RAG pgvector)
  ├─ micro_agents [Standard→Deep] (por linguagem detectada)
  ├─ domain_agents [Standard→Deep] (segurança, DBA, obs, perf...)
  └─ parse_ast [sem LLM] (tree-sitter call graph)
  ↓ (merge)
analyze [Deep] (consolida findings dos agentes)
  ↓
verify_critical [Verify] (segunda passada em findings críticos)
  ↓
deduplicate [Fast]
  ↓
score [Fast]
  ↓
generate_suggestions [Standard]
  ↓
feedback_ingestion [Fast] (se houver feedback anterior, atualiza knowledge)
  ↓
RETURN { findings, scores, suggestions, tokenUsage, agentBreakdown }
```

### 5.2 Variante quick

```
INPUT → pre_triage → dispatcher → micro_agents + retrieve_context → analyze → deduplicate → score → suggestions → RETURN
```
(Sem AST, sem verify, sem domain agents pesados)

### 5.3 Variante context

```
INPUT → context_discovery → RETURN { contextSummary }
```

---

## 6. Estrutura de Pastas (LangGraph.js best practices)

```
lumis-agent/
├── src/
│   ├── index.ts                      # Entry point: exporta runAnalysis()
│   │
│   ├── graph/
│   │   ├── index.ts                   # Compila e exporta o StateGraph
│   │   ├── state.ts                   # AgentState type definition
│   │   ├── routing.ts                 # Conditional edges (routeAfterTriage, etc)
│   │   └── types.ts                   # Tipos compartilhados (Finding, Score, etc)
│   │
│   ├── nodes/                         # Nós do grafo (funções puras async)
│   │   ├── index.ts                   # Re-exports
│   │   ├── preTriage.ts               # Classifica arquivos e linguagens
│   │   ├── contextDiscovery.ts        # Análise de contexto do repo
│   │   ├── dispatcher.ts              # Decide quais agentes ativar
│   │   ├── retrieveContext.ts         # RAG: pgvector → knowledge_chunks
│   │   ├── parseAst.ts                # AST / call graph (tree-sitter)
│   │   ├── microAgentsParallel.ts     # Orquestra micro agentes em paralelo
│   │   ├── domainAgentsParallel.ts    # Orquestra agentes de domínio em paralelo
│   │   ├── analyze.ts                 # Consolida findings dos agentes
│   │   ├── verifyCritical.ts          # Segunda passada em findings críticos
│   │   ├── deduplicate.ts             # Remove findings duplicados
│   │   ├── score.ts                   # Agrega scores por pilar
│   │   ├── generateSuggestions.ts     # Gera code patches
│   │   └── feedbackIngestion.ts       # Processa feedback → knowledge_chunks
│   │
│   ├── agents/                        # Agentes especializados (callables)
│   │   ├── index.ts
│   │   ├── BaseAgent.ts               # Classe base: mode, prompt loading, output parsing
│   │   ├── domain/
│   │   │   ├── index.ts
│   │   │   ├── SecurityAgent.ts       # OWASP, secrets, injection (Deep+Verify)
│   │   │   ├── DbaAgent.ts            # Queries, migrations, N+1 (Deep)
│   │   │   ├── ApiContractsAgent.ts   # REST, validação (Standard)
│   │   │   ├── TestingAgent.ts        # Cobertura, gaps (Standard)
│   │   │   ├── ObservabilityAgent.ts  # Logging, tracing, métricas (Deep)
│   │   │   ├── PerformanceAgent.ts    # Bottlenecks, cache (Deep)
│   │   │   ├── ArchitectureAgent.ts   # Acoplamento, padrões (Deep)
│   │   │   ├── DependenciesAgent.ts   # CVEs, licenças (Fast)
│   │   │   ├── DevOpsAgent.ts         # Docker, CI/CD (Standard)
│   │   │   └── LoggingObsAgent.ts     # Log levels, correlation (Standard)
│   │   └── languages/
│   │       ├── index.ts
│   │       ├── NodeTypescriptAgent.ts
│   │       ├── GolangAgent.ts
│   │       ├── PythonAgent.ts
│   │       ├── RustAgent.ts
│   │       ├── JavaKotlinAgent.ts
│   │       ├── CppAgent.ts
│   │       ├── ReactFrontendAgent.ts
│   │       └── IacTerraformAgent.ts
│   │
│   ├── prompts/                       # System prompts (arquivos .md)
│   │   ├── index.ts                   # loadPrompt() utility
│   │   ├── modes.ts                   # PromptMode enum + configs (temp, maxTokens)
│   │   ├── domain/
│   │   │   ├── security.md
│   │   │   ├── dba.md
│   │   │   ├── api-contracts.md
│   │   │   ├── testing.md
│   │   │   ├── observability.md
│   │   │   ├── performance.md
│   │   │   ├── architecture.md
│   │   │   ├── dependencies.md
│   │   │   ├── devops.md
│   │   │   └── logging-obs.md
│   │   └── languages/
│   │       ├── node-typescript.md
│   │       ├── golang.md
│   │       ├── python.md
│   │       ├── rust.md
│   │       ├── java-kotlin.md
│   │       ├── cpp.md
│   │       ├── react-frontend.md
│   │       └── iac-terraform.md
│   │
│   ├── llm/                           # Abstração do LLM
│   │   ├── index.ts
│   │   ├── client.ts                  # QwenClient: wrapper vLLM API (fetch)
│   │   ├── config.ts                  # LLM settings (endpoint, model, timeout)
│   │   └── outputParsers.ts           # JSON parsers, Finding validator
│   │
│   ├── knowledge/                     # Base de conhecimento (pgvector)
│   │   ├── index.ts
│   │   ├── db.ts                      # Pool de conexão pg (apenas knowledge_chunks)
│   │   ├── chunker.ts                 # Split por heading, code block, paragraph
│   │   ├── embedder.ts                # Gera embeddings via API
│   │   ├── retriever.ts               # pgvector search + filtros + re-ranking
│   │   ├── ingester.ts                # content → chunk → embed → upsert
│   │   ├── deduplicator.ts            # Cosine similarity threshold
│   │   └── pipelines/
│   │       ├── index.ts
│   │       ├── seed.ts                # CLI: popula base estática
│   │       ├── tenantUpload.ts        # Processa upload do tenant (chamado via API)
│   │       ├── analysisExtractor.ts   # Extrai padrões de análises completadas
│   │       ├── feedbackProcessor.ts   # Processa feedback → novos chunks
│   │       └── crossRepoAnalyzer.ts   # Padrões cross-repo (batch)
│   │
│   └── utils/
│       ├── index.ts
│       ├── fileReader.ts              # Lê arquivos do repoPath com limites
│       ├── astParser.ts               # Tree-sitter wrapper
│       └── logger.ts                  # Structured logging
│
├── knowledge/                         # Conteúdo estático (seed)
│   └── static/
│       ├── otel/
│       │   ├── tracing.md
│       │   ├── metrics.md
│       │   └── logging.md
│       ├── datadog/
│       │   ├── apm.md
│       │   └── logging.md
│       ├── security/
│       │   ├── owasp-top10.md
│       │   └── secrets.md
│       ├── languages/
│       │   ├── node-typescript.md
│       │   ├── golang.md
│       │   ├── python.md
│       │   ├── rust.md
│       │   ├── java-kotlin.md
│       │   └── cpp.md
│       ├── architecture/
│       │   ├── clean-architecture.md
│       │   ├── hexagonal.md
│       │   └── api-design.md
│       └── devops/
│           ├── docker.md
│           ├── terraform.md
│           └── kubernetes.md
│
├── tests/
│   ├── graph/
│   │   ├── graph.test.ts              # Integration test do grafo completo
│   │   └── routing.test.ts
│   ├── nodes/
│   │   ├── dispatcher.test.ts
│   │   ├── verifyCritical.test.ts
│   │   └── feedbackIngestion.test.ts
│   ├── agents/
│   │   ├── SecurityAgent.test.ts
│   │   ├── NodeTypescriptAgent.test.ts
│   │   └── GolangAgent.test.ts
│   ├── knowledge/
│   │   ├── retriever.test.ts
│   │   ├── ingester.test.ts
│   │   └── seed.test.ts
│   └── fixtures/
│       ├── sample-node-code.ts
│       ├── sample-go-code.go
│       └── sample-vulnerable-code.ts
│
├── package.json
├── tsconfig.json
├── .env
└── README.md
```

---

## 7. Tipos TypeScript (Contratos)

### 7.1 Input (o que o caller envia)

```typescript
// src/graph/types.ts

export interface AnalysisRequest {
  jobId: string;
  tenantId: string;
  repoId: string;
  repoPath: string;                    // Path do clone já feito pelo caller
  changedFiles: string[];              // Lista de paths relativos
  analysisType: 'quick' | 'full' | 'repository' | 'context';
  repoContext: RepoContext;
  previousFindings?: Finding[];        // Para diff crossrun
  feedbackHistory?: FeedbackSignal[];   // Para calibração
}

export interface RepoContext {
  languages: string[];                 // ['typescript', 'go', 'sql']
  repoType: 'backend' | 'frontend' | 'infra' | 'monorepo' | 'library';
  observabilityBackend?: string;       // 'datadog' | 'grafana' | null
  appSubtype?: string;
  iacProvider?: string;
  instrumentation?: string;
  obsMetadata?: Record<string, unknown>;
  contextSummary?: string;
}

export interface FeedbackSignal {
  findingTitle: string;
  pillar: string;
  signal: 'thumbs_up' | 'thumbs_down' | 'ignored' | 'applied';
  note?: string;
}
```

### 7.2 Output (o que retorna ao caller)

```typescript
export interface AnalysisResult {
  findings: Finding[];
  scores: Scores;
  suggestions: Suggestion[];
  tokenUsage: TokenUsage;
  agentBreakdown: Record<string, AgentStats>;
  contextSummary?: string;             // Só para analysisType='context'
}

export interface Finding {
  severity: 'critical' | 'warning' | 'info';
  title: string;
  description: string;
  filePath: string;
  lineStart: number;
  lineEnd?: number;
  suggestion?: string;
  pillar: 'coverage' | 'metrics' | 'efficiency' | 'compliance' | 'security';
  dimension?: string;
  confidence: number;                  // 0-1
  sourceAgent: string;                 // 'μ-node', 'D-security', etc
  promptMode: 'fast' | 'standard' | 'deep' | 'verify';
  verified: boolean;                   // passou pelo verify pass?
  reasoningExcerpt?: string;           // resumo do campo reasoning do LLM
  estimatedMonthlyCostImpact?: number;
}

export interface Scores {
  global: number;
  coverage: number;
  metrics: number;
  efficiency: number;
  compliance: number;
  security: number;
}

export interface Suggestion {
  findingTitle: string;
  filePath: string;
  codeBefore?: string;
  codeAfter: string;
  explanation: string;
}

export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
}

export interface AgentStats {
  mode: string;
  calls: number;
  promptTokens: number;
  completionTokens: number;
  findingsCount: number;
}
```

### 7.3 Estado do Grafo (interno)

```typescript
// src/graph/state.ts

import { Annotation } from '@langchain/langgraph';

export const AgentState = Annotation.Root({
  // Input (do caller)
  request: Annotation<AnalysisRequest>,
  
  // Contexto construído pelos nós
  classifiedFiles: Annotation<ClassifiedFile[]>({ default: () => [] }),
  detectedLanguages: Annotation<string[]>({ default: () => [] }),
  detectedArtifacts: Annotation<string[]>({ default: () => [] }),
  activeAgents: Annotation<string[]>({ default: () => [] }),
  
  // RAG
  ragContext: Annotation<RagChunk[]>({ default: () => [] }),
  
  // AST
  callGraph: Annotation<Record<string, string[]>>({ default: () => ({}) }),
  
  // Findings acumulados (reducer: merge)
  findings: Annotation<Finding[]>({
    default: () => [],
    reducer: (current, update) => [...current, ...update],
  }),
  
  // Scores
  scores: Annotation<Scores | null>({ default: () => null }),
  
  // Sugestões
  suggestions: Annotation<Suggestion[]>({ default: () => [] }),
  
  // Token usage tracking
  tokenUsage: Annotation<TokenUsage>({
    default: () => ({ promptTokens: 0, completionTokens: 0, totalTokens: 0 }),
    reducer: (current, update) => ({
      promptTokens: current.promptTokens + update.promptTokens,
      completionTokens: current.completionTokens + update.completionTokens,
      totalTokens: current.totalTokens + update.totalTokens,
    }),
  }),
  
  // Agent breakdown
  agentBreakdown: Annotation<Record<string, AgentStats>>({
    default: () => ({}),
    reducer: (current, update) => ({ ...current, ...update }),
  }),
});

export type AgentStateType = typeof AgentState.State;
```

---

## 8. LLM Client (TypeScript)

```typescript
// src/llm/client.ts

export enum PromptMode {
  FAST = 'fast',
  STANDARD = 'standard',
  DEEP = 'deep',
  VERIFY = 'verify',
}

const MODE_CONFIGS: Record<PromptMode, { temperature: number; top_p: number; max_tokens: number }> = {
  [PromptMode.FAST]:     { temperature: 0.1, top_p: 0.9,  max_tokens: 1024 },
  [PromptMode.STANDARD]: { temperature: 0.3, top_p: 0.9,  max_tokens: 2048 },
  [PromptMode.DEEP]:     { temperature: 0.4, top_p: 0.9,  max_tokens: 4096 },
  [PromptMode.VERIFY]:   { temperature: 0.2, top_p: 0.85, max_tokens: 1024 },
};

export interface LLMResponse {
  content: string;
  reasoning?: string;
  promptTokens: number;
  completionTokens: number;
  finishReason: string;
}

export class QwenClient {
  constructor(
    private baseUrl: string,
    private model: string,
    private timeout: number = 60_000,
  ) {}

  async call(
    systemPrompt: string,
    userPrompt: string,
    mode: PromptMode = PromptMode.STANDARD,
    maxRetries: number = 3,
  ): Promise<LLMResponse> {
    const config = { ...MODE_CONFIGS[mode] };

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const resp = await fetch(`${this.baseUrl}/v1/chat/completions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: this.model,
            messages: [
              { role: 'system', content: systemPrompt },
              { role: 'user', content: userPrompt },
            ],
            stream: false,
            ...config,
          }),
          signal: AbortSignal.timeout(this.timeout),
        });

        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
        }

        const data = await resp.json();
        const choice = data.choices[0];
        const msg = choice.message;

        const result: LLMResponse = {
          content: (msg.content ?? '').trim(),
          reasoning: msg.reasoning ?? undefined,
          promptTokens: data.usage.prompt_tokens,
          completionTokens: data.usage.completion_tokens,
          finishReason: choice.finish_reason,
        };

        // Retry com mais tokens se cortou
        if (result.finishReason === 'length') {
          config.max_tokens = Math.floor(config.max_tokens * 1.5);
          continue;
        }

        return result;
      } catch (err) {
        if (attempt === maxRetries - 1) throw err;
        await new Promise(r => setTimeout(r, 2 ** attempt * 1000));
      }
    }

    throw new Error(`Max retries (${maxRetries}) exceeded`);
  }
}
```

---

## 9. Knowledge Base — Acesso ao pgvector

### 9.1 Conexão (apenas knowledge_chunks)

```typescript
// src/knowledge/db.ts

import pg from 'pg';

const pool = new pg.Pool({
  connectionString: process.env.DATABASE_URL,
  // postgresql://sre:local_only@192.168.15.14:5432/lumis
  max: 10,
  idleTimeoutMillis: 30_000,
});

export { pool };
```

### 9.2 Retriever (busca RAG)

```typescript
// src/knowledge/retriever.ts

import { pool } from './db';
import { embedder } from './embedder';

export interface RagChunk {
  id: string;
  content: string;
  sourceType: string;
  language: string | null;
  pillar: string | null;
  similarity: number;
  metadata: Record<string, unknown>;
}

export async function retrieveContext(
  query: string,
  tenantId: string,
  filters: { language?: string; pillar?: string },
  limit: number = 10,
): Promise<RagChunk[]> {
  const queryEmbedding = await embedder.embed(query);

  const result = await pool.query<RagChunk>(
    `SELECT 
       id, content, source_type AS "sourceType",
       language, pillar, metadata,
       1 - (embedding <=> $1::vector) AS similarity
     FROM knowledge_chunks
     WHERE (tenant_id = $2 OR tenant_id IS NULL)
       AND ($3::text IS NULL OR language = $3 OR language IS NULL)
       AND ($4::text IS NULL OR pillar = $4 OR pillar IS NULL)
       AND (expires_at IS NULL OR expires_at > NOW())
     ORDER BY embedding <=> $1::vector
     LIMIT $5`,
    [
      JSON.stringify(queryEmbedding),
      tenantId,
      filters.language ?? null,
      filters.pillar ?? null,
      limit,
    ],
  );

  return result.rows;
}
```

### 9.3 Ingester (escreve chunks)

```typescript
// src/knowledge/ingester.ts

import { pool } from './db';
import { embedder } from './embedder';
import { chunker } from './chunker';

export async function ingestContent(params: {
  tenantId: string | null;
  sourceType: string;
  content: string;
  language?: string;
  pillar?: string;
  repoId?: string;
  metadata?: Record<string, unknown>;
}): Promise<void> {
  const chunks = chunker.splitByHeading(params.content, {
    maxTokens: 1500,
    overlapTokens: 200,
  });

  for (const chunk of chunks) {
    const embedding = await embedder.embed(chunk.text);

    await pool.query(
      `INSERT INTO knowledge_chunks 
         (tenant_id, source_type, content, embedding, metadata, language, pillar, repo_id)
       VALUES ($1, $2, $3, $4::vector, $5, $6, $7, $8)
       ON CONFLICT DO NOTHING`,
      [
        params.tenantId,
        params.sourceType,
        chunk.text,
        JSON.stringify(embedding),
        { ...params.metadata, heading: chunk.heading },
        params.language ?? null,
        params.pillar ?? null,
        params.repoId ?? null,
      ],
    );
  }
}
```

---

## 10. Pipelines de Knowledge Base

### 10.1 Seed (estático — CLI)

**Quando:** Deploy, atualização de docs  
**Comando:** `npx tsx src/knowledge/pipelines/seed.ts --source otel`

```
knowledge/static/*.md (versionados no Git)
  ↓
Parse frontmatter YAML (language, pillar, source_type)
  ↓
Split por ## heading (max 1500 tokens, overlap 200)
  ↓
Embedding (API de embedding)
  ↓
Upsert no knowledge_chunks (idempotente via metadata.section_id)
```

### 10.2 Tenant Upload (chamado pelo serviço API)

**Quando:** Tenant faz upload via UI/API  
**Como:** O serviço API chama `ingestContent()` passando o conteúdo

```
API recebe Markdown do tenant
  ↓
Chama ingestContent({ tenantId, sourceType: 'tenant_standards', content, language })
  ↓
Chunking + embedding + persist com tenant_id
  ↓
RLS garante isolamento por tenant
```

### 10.3 Analysis Extractor (automático no grafo)

**Quando:** A cada análise completada (dentro do nó `feedbackIngestion`)  
**Trigger:** Findings com confidence ≥ 0.8 ou recorrentes (>3x no diff_crossrun)

```
Findings relevantes da análise
  ↓
Qwen Fast sintetiza o padrão em texto descritivo
  ↓
Dedup (cosine > 0.95 com chunks existentes = skip)
  ↓
Persist: source_type='analysis_history'
```

### 10.4 Feedback Processor (batch ou inline)

**Quando:** Feedback acumulado ≥3 sinais para mesmo finding title  
**Trigger:** O caller envia `feedbackHistory` no próximo `runAnalysis()`

```
feedbackHistory do caller
  ↓
Agrega por title + pillar
  ↓
≥3 thumbs_up = confirmed pattern → gera chunk positivo
≥3 thumbs_down = false positive → gera chunk de calibração
  ↓
Persist: source_type='feedback_derived', confidence_score baseado no ratio
  ↓
Próxima análise: retrieve_context injeta esses chunks → agente calibrado
```

### 10.5 Cross-Repo (batch chamado externamente)

**Quando:** Semanal  
**Como:** O caller invoca `runCrossRepoAnalysis(tenantId)`

```
Busca findings dos últimos 30 dias de todos repos do tenant
  ↓
Clustering por embedding (cosine > 0.85)
  ↓
Clusters com >3 repos = padrão cross-repo
  ↓
Qwen Standard gera descrição do padrão
  ↓
Persist: source_type='cross_repo_pattern'
```

---

## 11. Entry Point

```typescript
// src/index.ts

import { analysisGraph } from './graph';
import { pool } from './knowledge/db';
import type { AnalysisRequest, AnalysisResult } from './graph/types';

export async function runAnalysis(request: AnalysisRequest): Promise<AnalysisResult> {
  const initialState = {
    request,
    classifiedFiles: [],
    detectedLanguages: [],
    detectedArtifacts: [],
    activeAgents: [],
    ragContext: [],
    callGraph: {},
    findings: [],
    scores: null,
    suggestions: [],
    tokenUsage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 },
    agentBreakdown: {},
  };

  const finalState = await analysisGraph.invoke(initialState);

  return {
    findings: finalState.findings,
    scores: finalState.scores!,
    suggestions: finalState.suggestions,
    tokenUsage: finalState.tokenUsage,
    agentBreakdown: finalState.agentBreakdown,
    contextSummary: request.analysisType === 'context' 
      ? finalState.contextSummary 
      : undefined,
  };
}

// Para pipelines de knowledge base chamados externamente
export { ingestContent } from './knowledge/ingester';
export { retrieveContext } from './knowledge/retriever';
export { seedKnowledge } from './knowledge/pipelines/seed';
export { processFeedbackBatch } from './knowledge/pipelines/feedbackProcessor';
export { runCrossRepoAnalysis } from './knowledge/pipelines/crossRepoAnalyzer';

// Cleanup
export async function shutdown(): Promise<void> {
  await pool.end();
}
```

---

## 12. Configuração

### 12.1 package.json

```json
{
  "name": "@lumis/agent",
  "version": "1.0.0",
  "type": "module",
  "main": "dist/index.js",
  "types": "dist/index.d.ts",
  "scripts": {
    "build": "tsc",
    "dev": "tsx watch src/index.ts",
    "test": "vitest",
    "seed": "tsx src/knowledge/pipelines/seed.ts",
    "lint": "eslint src/"
  },
  "dependencies": {
    "@langchain/langgraph": "^0.2",
    "@langchain/core": "^0.3",
    "pg": "^8.13",
    "pgvector": "^0.2",
    "tree-sitter": "^0.22",
    "zod": "^3.23"
  },
  "devDependencies": {
    "typescript": "^5.6",
    "tsx": "^4.19",
    "vitest": "^2.1",
    "@types/pg": "^8.11",
    "eslint": "^9.0"
  }
}
```

### 12.2 tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "resolveJsonModule": true,
    "skipLibCheck": true
  },
  "include": ["src"],
  "exclude": ["node_modules", "dist", "tests"]
}
```

### 12.3 .env

```env
# Qwen 3.5 via vLLM
QWEN_API_URL=http://52.86.35.131:8001
QWEN_MODEL=Qwen/Qwen3.5-35B-A3B-FP8
QWEN_TIMEOUT=60000
QWEN_MAX_RETRIES=3

# PostgreSQL (pgvector) — apenas para knowledge_chunks
DATABASE_URL=postgresql://sre:local_only@192.168.15.14:5432/lumis
```

---

## 13. Resumo do Ciclo de Vida

```
[Serviço externo] → runAnalysis(request) → [lumis-agent]
                                                ↓
                                          pre_triage (Qwen Fast)
                                                ↓
                                          dispatcher (Qwen Fast)
                                                ↓
                                     ┌──────────┼──────────┐
                                     ↓          ↓          ↓
                                   RAG      μ-agents   domain-agents
                                 (pgvector)  (por lang)  (sec,dba,obs)
                                     └──────────┼──────────┘
                                                ↓
                                          analyze + verify
                                                ↓
                                       dedup → score → suggestions
                                                ↓
                                       feedback_ingestion
                                          (atualiza knowledge_chunks)
                                                ↓
                                  return { findings, scores, suggestions }
                                                ↓
[Serviço externo] ← AnalysisResult ← [lumis-agent]
     ↓
     persiste em analysis_results, findings, comenta PR, atualiza billing
```

O agente é **stateless** — toda persistência de jobs, billing e PR comments é responsabilidade do caller. A única escrita que o agente faz no banco é em `knowledge_chunks` (base de conhecimento RAG).

---

## 14. Alterações no Banco de Dados

> **Conexão:** `postgresql://sre:local_only@192.168.15.14:5432/lumis`  
> **Importante:** Todas as alterações são **aditivas** (ADD COLUMN, novos ENUMs, novos índices). Nenhuma coluna existente é removida ou renomeada. Zero breaking changes.

### 14.1 Novos valores de ENUM

```sql
-- ═══════════════════════════════════════════════
-- NOVOS VALORES DE ENUM
-- ═══════════════════════════════════════════════

-- pillar_enum: adicionar novos pilares (se não existirem)
-- Valores existentes: coverage, metrics, efficiency, compliance, security
-- Nenhum novo valor necessário — os 5 pilares cobrem todos os agentes.

-- severity_enum: sem mudança
-- Valores existentes: critical, warning, info

-- dimension_enum: novos valores para dimensões dos agentes
-- Se dimension_enum for extensível, adicionar:
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'injection';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'query_optimization';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'distributed_tracing';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'error_handling';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'migration_safety';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'test_coverage';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'dockerfile_best_practices';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'goroutine_safety';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'memory_safety';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'ownership_lifetime';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'async_patterns';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'dependency_vulnerability';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'api_contract';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'architecture_coupling';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'logging_structure';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'resource_limits';
ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'secret_exposure';

-- analysis_type_enum: sem mudança
-- Valores existentes: quick, full, repository, context
```

### 14.2 Tabela `analysis_results` — Novas colunas

```sql
-- ═══════════════════════════════════════════════
-- ANALYSIS_RESULTS: rastreamento por agente
-- ═══════════════════════════════════════════════

-- Breakdown de custo/tokens/calls por agente
-- Exemplo: {"D-security": {"mode":"deep","calls":2,"promptTokens":9500,"completionTokens":4100,"findingsCount":1}}
ALTER TABLE analysis_results
  ADD COLUMN IF NOT EXISTS agent_breakdown JSONB DEFAULT '{}';

-- Modos de prompt utilizados nesta análise
-- Exemplo: ['fast','standard','deep','verify']
ALTER TABLE analysis_results
  ADD COLUMN IF NOT EXISTS prompt_modes_used TEXT[] DEFAULT '{}';

-- Total de passadas (multi-pass: triagem + análise + verify)
ALTER TABLE analysis_results
  ADD COLUMN IF NOT EXISTS total_passes INTEGER DEFAULT 1;

-- Modelo LLM utilizado (para tracking quando trocar modelo)
-- Exemplo: 'Qwen/Qwen3.5-35B-A3B-FP8'
ALTER TABLE analysis_results
  ADD COLUMN IF NOT EXISTS llm_model TEXT;

-- Agentes que foram ativados nesta análise
-- Exemplo: ['D-security','D-dba','D-observability','μ-node-typescript']
ALTER TABLE analysis_results
  ADD COLUMN IF NOT EXISTS active_agents TEXT[] DEFAULT '{}';

-- Linguagens detectadas pelo pre_triage
-- Exemplo: ['typescript','sql']
ALTER TABLE analysis_results
  ADD COLUMN IF NOT EXISTS detected_languages TEXT[] DEFAULT '{}';

COMMENT ON COLUMN analysis_results.agent_breakdown IS 'JSONB: breakdown de tokens, calls e findings por agente. Chave = sourceAgent (ex: D-security, μ-node-typescript)';
COMMENT ON COLUMN analysis_results.prompt_modes_used IS 'Array de modos de prompt utilizados: fast, standard, deep, verify';
COMMENT ON COLUMN analysis_results.total_passes IS 'Total de passadas de LLM (inclui verify pass)';
COMMENT ON COLUMN analysis_results.llm_model IS 'Identificador do modelo LLM usado (ex: Qwen/Qwen3.5-35B-A3B-FP8)';
COMMENT ON COLUMN analysis_results.active_agents IS 'Agentes ativados pelo dispatcher nesta análise';
COMMENT ON COLUMN analysis_results.detected_languages IS 'Linguagens detectadas pelo pre_triage no repositório';
```

### 14.3 Tabela `findings` — Novas colunas

```sql
-- ═══════════════════════════════════════════════
-- FINDINGS: rastreabilidade por agente e verificação
-- ═══════════════════════════════════════════════

-- Qual agente gerou este finding
-- Prefixos: μ- = micro agente de linguagem, D- = agente de domínio
-- Exemplo: 'μ-node-typescript', 'D-security', 'D-dba'
ALTER TABLE findings
  ADD COLUMN IF NOT EXISTS source_agent TEXT;

-- Modo de prompt usado para gerar este finding
-- Exemplo: 'fast', 'standard', 'deep', 'verify'
ALTER TABLE findings
  ADD COLUMN IF NOT EXISTS prompt_mode TEXT;

-- Se o finding passou pelo verify pass (segunda passada de confirmação)
-- true = confirmado pelo agente Verify, false = não verificado (default)
ALTER TABLE findings
  ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT false;

-- Confiança do modelo neste finding (0.0 a 1.0)
-- Findings com confidence < 0.7 são candidatos a verificação adicional
ALTER TABLE findings
  ADD COLUMN IF NOT EXISTS confidence FLOAT;

-- Resumo do campo 'reasoning' do LLM (chain-of-thought)
-- Presente apenas em findings gerados com modo Deep ou Verify
ALTER TABLE findings
  ADD COLUMN IF NOT EXISTS reasoning_excerpt TEXT;

-- Índices para consultas frequentes
CREATE INDEX IF NOT EXISTS idx_findings_source_agent ON findings(source_agent);
CREATE INDEX IF NOT EXISTS idx_findings_verified ON findings(verified);
CREATE INDEX IF NOT EXISTS idx_findings_confidence ON findings(confidence);

COMMENT ON COLUMN findings.source_agent IS 'Agente que gerou: μ-node-typescript, D-security, D-dba, etc';
COMMENT ON COLUMN findings.prompt_mode IS 'Modo de prompt: fast, standard, deep, verify';
COMMENT ON COLUMN findings.verified IS 'Passou pelo verify pass (segunda passada para findings críticos)';
COMMENT ON COLUMN findings.confidence IS 'Confiança do modelo 0.0-1.0. >=0.8 alta, <0.7 candidato a verify';
COMMENT ON COLUMN findings.reasoning_excerpt IS 'Resumo do chain-of-thought do LLM (modos Deep e Verify)';
```

### 14.4 Tabela `findings` JSONB — Novos campos dentro do JSONB de `analysis_results.findings`

```sql
-- ═══════════════════════════════════════════════
-- FINDINGS JSONB (snapshot dentro de analysis_results)
-- ═══════════════════════════════════════════════

-- O campo analysis_results.findings (JSONB) já existe e contém o snapshot
-- completo dos findings. Os novos campos dentro de CADA finding no JSONB são:
--
-- {
--   ... campos existentes (title, description, severity, pillar, etc) ...
--   "source_agent": "D-security",                  -- NOVO
--   "prompt_mode": "deep",                          -- NOVO
--   "verified": true,                               -- NOVO
--   "confidence": 0.95,                             -- NOVO
--   "reasoning_excerpt": "O input do usuário...",   -- NOVO
-- }
--
-- NENHUMA alteração de schema necessária — JSONB é schemaless.
-- O caller que persiste deve incluir estes campos ao gravar.
```

### 14.5 Tabela `knowledge_chunks` — Novas colunas e source_types

```sql
-- ═══════════════════════════════════════════════
-- KNOWLEDGE_CHUNKS: novas colunas para qualidade e tracking
-- ═══════════════════════════════════════════════

-- Confiança do chunk (0.0 a 1.0)
-- Chunks gerados por feedback com alta concordância têm score alto
-- Chunks de seed estático têm 1.0 por default
ALTER TABLE knowledge_chunks
  ADD COLUMN IF NOT EXISTS confidence_score FLOAT DEFAULT 1.0;

-- Qual modelo validou/gerou este chunk
-- Exemplo: 'Qwen/Qwen3.5-35B-A3B-FP8', ou null para chunks de seed
ALTER TABLE knowledge_chunks
  ADD COLUMN IF NOT EXISTS model_validated_by TEXT;

-- Versão do conteúdo fonte (para idempotência do seed)
-- Exemplo: 'otel-1.32', 'owasp-2025'
ALTER TABLE knowledge_chunks
  ADD COLUMN IF NOT EXISTS source_version TEXT;

-- ═══════════════════════════════════════════════
-- NOVOS SOURCE_TYPES (valores para a coluna source_type)
-- ═══════════════════════════════════════════════
--
-- Valores existentes:
--   'otel_docs'           — OpenTelemetry docs
--   'dd_docs'             — Datadog docs
--   'tenant_standards'    — Padrões do time
--   'analysis_history'    — Histórico de análises
--   'cross_repo_pattern'  — Padrões cross-repo
--
-- Novos valores a adicionar:
--   'grafana_docs'        — Grafana, Loki, Tempo, PromQL
--   'security_docs'       — OWASP Top 10, CWE, checklists
--   'language_docs'       — Best practices por linguagem (Go, Node, Python, etc)
--   'architecture_docs'   — Clean Architecture, Hexagonal, DDD
--   'devops_docs'         — Docker, Terraform, K8s, CI/CD best practices
--   'tenant_adrs'         — Architecture Decision Records do tenant
--   'tenant_runbooks'     — Runbooks, SOPs do tenant
--   'tenant_rules'        — Regras customizadas de análise do tenant
--   'feedback_derived'    — Chunks gerados a partir de finding_feedback
--   'agent_pattern'       — Padrões globais aprendidos pelos agentes
--   'verified_pattern'    — Padrões confirmados pelo verify pass
--   'repo_context'        — Resumo do repo gerado pelo context_discovery
--
-- Se source_type for TEXT (sem ENUM), nenhuma alteração necessária.
-- Se for ENUM, executar:
-- ALTER TYPE source_type_enum ADD VALUE IF NOT EXISTS 'grafana_docs';
-- ALTER TYPE source_type_enum ADD VALUE IF NOT EXISTS 'security_docs';
-- ... etc para cada valor acima

-- Índice para confidence (otimizar retrieval com threshold)
CREATE INDEX IF NOT EXISTS idx_kc_confidence ON knowledge_chunks(confidence_score);

-- Índice para source_version (idempotência do seed)
CREATE INDEX IF NOT EXISTS idx_kc_source_version ON knowledge_chunks(source_version);

COMMENT ON COLUMN knowledge_chunks.confidence_score IS 'Confiança 0.0-1.0. Seed=1.0, feedback_derived=baseado no ratio up/down';
COMMENT ON COLUMN knowledge_chunks.model_validated_by IS 'Modelo que gerou/validou: Qwen/Qwen3.5-35B-A3B-FP8 ou null para seed';
COMMENT ON COLUMN knowledge_chunks.source_version IS 'Versão do conteúdo fonte para idempotência (ex: otel-1.32)';
```

### 14.6 Tabela `knowledge_chunks` — Constraint de upsert para seed idempotente

```sql
-- ═══════════════════════════════════════════════
-- CONSTRAINT PARA UPSERT IDEMPOTENTE (SEED PIPELINE)
-- ═══════════════════════════════════════════════

-- O seed pipeline precisa fazer upsert sem duplicar chunks.
-- Usa a combinação (source_type, source_version, metadata->>'section_id')
-- como chave de unicidade.

-- Criar índice único parcial para seed (tenant_id IS NULL = global)
CREATE UNIQUE INDEX IF NOT EXISTS uq_kc_seed_section 
  ON knowledge_chunks (source_type, source_version, (metadata->>'section_id'))
  WHERE tenant_id IS NULL AND source_version IS NOT NULL;

-- Para chunks de tenant, unicidade por (tenant_id, source_type, metadata->>'section_id')
CREATE UNIQUE INDEX IF NOT EXISTS uq_kc_tenant_section 
  ON knowledge_chunks (tenant_id, source_type, (metadata->>'section_id'))
  WHERE tenant_id IS NOT NULL;
```

### 14.7 Tabela `repositories` — Nova coluna de configuração

```sql
-- ═══════════════════════════════════════════════
-- REPOSITORIES: configuração de análise por repo
-- ═══════════════════════════════════════════════

-- Configuração customizada de análise para este repo
-- Permite ao tenant configurar behavior por repo
ALTER TABLE repositories
  ADD COLUMN IF NOT EXISTS analysis_config JSONB DEFAULT '{}';

COMMENT ON COLUMN repositories.analysis_config IS 'Config de análise por repo. Exemplo: {"maxPasses":3,"verifyThreshold":"critical","disabledAgents":["D-devops"],"preferredAgents":["D-security","D-dba"]}';

-- Exemplos de analysis_config:
--
-- Repo com foco em segurança:
-- {
--   "maxPasses": 3,
--   "verifyThreshold": "warning",        -- verifica findings warning+ (não só critical)
--   "preferredAgents": ["D-security"],    -- sempre ativa segurança mesmo em quick
--   "disabledAgents": [],
--   "customPromptOverrides": {}           -- futuro: override de prompts por repo
-- }
--
-- Repo legacy que gera muitos falsos positivos:
-- {
--   "maxPasses": 1,
--   "verifyThreshold": "critical",
--   "preferredAgents": [],
--   "disabledAgents": ["D-architecture", "D-testing"],  -- desativa agentes ruidosos
--   "ignorePatterns": ["src/legacy/**"]                  -- ignora paths
-- }
--
-- Repo de IaC puro:
-- {
--   "maxPasses": 2,
--   "verifyThreshold": "critical",
--   "preferredAgents": ["μ-iac-terraform", "D-security", "D-devops"],
--   "disabledAgents": ["D-dba", "D-testing"]
-- }
```

### 14.8 Tabela `finding_feedback` — Nova coluna (opcional)

```sql
-- ═══════════════════════════════════════════════
-- FINDING_FEEDBACK: contexto adicional para aprendizado
-- ═══════════════════════════════════════════════

-- Qual agente gerou o finding que recebeu feedback
-- Permite rastrear quais agentes estão gerando mais falsos positivos
ALTER TABLE finding_feedback
  ADD COLUMN IF NOT EXISTS source_agent TEXT;

-- Se o feedback já foi processado pelo pipeline de feedback
-- Evita reprocessar o mesmo feedback
ALTER TABLE finding_feedback
  ADD COLUMN IF NOT EXISTS processed BOOLEAN DEFAULT false;

-- Quando foi processado
ALTER TABLE finding_feedback
  ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ff_processed ON finding_feedback(processed) WHERE processed = false;
CREATE INDEX IF NOT EXISTS idx_ff_source_agent ON finding_feedback(source_agent);

COMMENT ON COLUMN finding_feedback.source_agent IS 'Agente que gerou o finding original (D-security, μ-node-typescript, etc)';
COMMENT ON COLUMN finding_feedback.processed IS 'Se este feedback já foi processado pelo pipeline de feedback_ingestion';
COMMENT ON COLUMN finding_feedback.processed_at IS 'Timestamp de quando foi processado';
```

### 14.9 Extensão pgvector — Verificar instalação

```sql
-- ═══════════════════════════════════════════════
-- PGVECTOR: garantir que a extensão está instalada
-- ═══════════════════════════════════════════════

-- Já deve existir (migration anterior criou). Verificar:
CREATE EXTENSION IF NOT EXISTS vector;

-- Verificar que o índice HNSW existe:
-- Se não existir, criar:
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding 
  ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

-- Índices de filtro para performance do retriever:
CREATE INDEX IF NOT EXISTS idx_kc_tenant ON knowledge_chunks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_kc_source ON knowledge_chunks(source_type);
CREATE INDEX IF NOT EXISTS idx_kc_lang ON knowledge_chunks(language);
CREATE INDEX IF NOT EXISTS idx_kc_pillar ON knowledge_chunks(pillar);
CREATE INDEX IF NOT EXISTS idx_kc_repo ON knowledge_chunks(repo_id);
CREATE INDEX IF NOT EXISTS idx_kc_expires ON knowledge_chunks(expires_at) WHERE expires_at IS NOT NULL;
```

### 14.10 Script de migração completo (executar uma vez)

```sql
-- ═══════════════════════════════════════════════════════════════════
-- LUMIS — MIGRATION: Multi-Agent Support
-- ═══════════════════════════════════════════════════════════════════
-- 
-- Descrição: Adiciona colunas e índices para suportar arquitetura 
--            multi-agente com Qwen 3.5, micro agentes por linguagem,
--            e base de conhecimento enriquecida.
--
-- Pré-requisitos: pgvector já instalado, tabelas existentes intactas
-- Risco: BAIXO (apenas ADD COLUMN, CREATE INDEX, aditivo)
-- Rollback: DROP COLUMN / DROP INDEX (listado no final)
--
-- Conexão: postgresql://sre:local_only@192.168.15.14:5432/lumis
-- ═══════════════════════════════════════════════════════════════════

BEGIN;

-- 1. Extensão pgvector (idempotente)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. analysis_results
ALTER TABLE analysis_results
  ADD COLUMN IF NOT EXISTS agent_breakdown JSONB DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS prompt_modes_used TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS total_passes INTEGER DEFAULT 1,
  ADD COLUMN IF NOT EXISTS llm_model TEXT,
  ADD COLUMN IF NOT EXISTS active_agents TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS detected_languages TEXT[] DEFAULT '{}';

-- 3. findings
ALTER TABLE findings
  ADD COLUMN IF NOT EXISTS source_agent TEXT,
  ADD COLUMN IF NOT EXISTS prompt_mode TEXT,
  ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS confidence FLOAT,
  ADD COLUMN IF NOT EXISTS reasoning_excerpt TEXT;

CREATE INDEX IF NOT EXISTS idx_findings_source_agent ON findings(source_agent);
CREATE INDEX IF NOT EXISTS idx_findings_verified ON findings(verified);
CREATE INDEX IF NOT EXISTS idx_findings_confidence ON findings(confidence);

-- 4. knowledge_chunks
ALTER TABLE knowledge_chunks
  ADD COLUMN IF NOT EXISTS confidence_score FLOAT DEFAULT 1.0,
  ADD COLUMN IF NOT EXISTS model_validated_by TEXT,
  ADD COLUMN IF NOT EXISTS source_version TEXT;

CREATE INDEX IF NOT EXISTS idx_kc_confidence ON knowledge_chunks(confidence_score);
CREATE INDEX IF NOT EXISTS idx_kc_source_version ON knowledge_chunks(source_version);

CREATE UNIQUE INDEX IF NOT EXISTS uq_kc_seed_section 
  ON knowledge_chunks (source_type, source_version, (metadata->>'section_id'))
  WHERE tenant_id IS NULL AND source_version IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_kc_tenant_section 
  ON knowledge_chunks (tenant_id, source_type, (metadata->>'section_id'))
  WHERE tenant_id IS NOT NULL;

-- Índices de filtro para retriever (idempotente)
CREATE INDEX IF NOT EXISTS idx_kc_tenant ON knowledge_chunks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_kc_source ON knowledge_chunks(source_type);
CREATE INDEX IF NOT EXISTS idx_kc_lang ON knowledge_chunks(language);
CREATE INDEX IF NOT EXISTS idx_kc_pillar ON knowledge_chunks(pillar);
CREATE INDEX IF NOT EXISTS idx_kc_repo ON knowledge_chunks(repo_id);
CREATE INDEX IF NOT EXISTS idx_kc_expires ON knowledge_chunks(expires_at) WHERE expires_at IS NOT NULL;

-- HNSW index (se não existir)
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding 
  ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

-- 5. repositories
ALTER TABLE repositories
  ADD COLUMN IF NOT EXISTS analysis_config JSONB DEFAULT '{}';

-- 6. finding_feedback
ALTER TABLE finding_feedback
  ADD COLUMN IF NOT EXISTS source_agent TEXT,
  ADD COLUMN IF NOT EXISTS processed BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ff_processed ON finding_feedback(processed) WHERE processed = false;
CREATE INDEX IF NOT EXISTS idx_ff_source_agent ON finding_feedback(source_agent);

-- 7. dimension_enum (se existir como ENUM, adicionar valores)
-- NOTA: Descomentar apenas se dimension for ENUM. Se for TEXT, ignorar.
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'injection';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'query_optimization';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'distributed_tracing';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'error_handling';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'migration_safety';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'test_coverage';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'dockerfile_best_practices';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'goroutine_safety';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'memory_safety';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'ownership_lifetime';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'async_patterns';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'dependency_vulnerability';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'api_contract';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'architecture_coupling';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'logging_structure';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'resource_limits';
-- ALTER TYPE dimension_enum ADD VALUE IF NOT EXISTS 'secret_exposure';

COMMIT;

-- ═══════════════════════════════════════════════
-- ROLLBACK (caso precise reverter)
-- ═══════════════════════════════════════════════
-- 
-- ALTER TABLE analysis_results
--   DROP COLUMN IF EXISTS agent_breakdown,
--   DROP COLUMN IF EXISTS prompt_modes_used,
--   DROP COLUMN IF EXISTS total_passes,
--   DROP COLUMN IF EXISTS llm_model,
--   DROP COLUMN IF EXISTS active_agents,
--   DROP COLUMN IF EXISTS detected_languages;
--
-- ALTER TABLE findings
--   DROP COLUMN IF EXISTS source_agent,
--   DROP COLUMN IF EXISTS prompt_mode,
--   DROP COLUMN IF EXISTS verified,
--   DROP COLUMN IF EXISTS confidence,
--   DROP COLUMN IF EXISTS reasoning_excerpt;
--
-- ALTER TABLE knowledge_chunks
--   DROP COLUMN IF EXISTS confidence_score,
--   DROP COLUMN IF EXISTS model_validated_by,
--   DROP COLUMN IF EXISTS source_version;
--
-- ALTER TABLE repositories
--   DROP COLUMN IF EXISTS analysis_config;
--
-- ALTER TABLE finding_feedback
--   DROP COLUMN IF EXISTS source_agent,
--   DROP COLUMN IF EXISTS processed,
--   DROP COLUMN IF EXISTS processed_at;
--
-- DROP INDEX IF EXISTS idx_findings_source_agent;
-- DROP INDEX IF EXISTS idx_findings_verified;
-- DROP INDEX IF EXISTS idx_findings_confidence;
-- DROP INDEX IF EXISTS idx_kc_confidence;
-- DROP INDEX IF EXISTS idx_kc_source_version;
-- DROP INDEX IF EXISTS uq_kc_seed_section;
-- DROP INDEX IF EXISTS uq_kc_tenant_section;
-- DROP INDEX IF EXISTS idx_ff_processed;
-- DROP INDEX IF EXISTS idx_ff_source_agent;
```

### 14.11 Resumo das alterações

| Tabela | Colunas adicionadas | Índices | Risco |
|--------|--------------------|---------| ------|
| `analysis_results` | `agent_breakdown`, `prompt_modes_used`, `total_passes`, `llm_model`, `active_agents`, `detected_languages` | — | Baixo |
| `findings` | `source_agent`, `prompt_mode`, `verified`, `confidence`, `reasoning_excerpt` | 3 índices | Baixo |
| `knowledge_chunks` | `confidence_score`, `model_validated_by`, `source_version` | 2 índices + 2 unique parciais + 6 índices de filtro + 1 HNSW | Baixo |
| `repositories` | `analysis_config` | — | Baixo |
| `finding_feedback` | `source_agent`, `processed`, `processed_at` | 2 índices | Baixo |
| **Total** | **19 colunas** | **16 índices** | **Baixo** |

Todas as alterações usam `ADD COLUMN IF NOT EXISTS` e `CREATE INDEX IF NOT EXISTS` — **seguro para rodar múltiplas vezes** (idempotente).

---

*Documento para contexto do Cursor. Runtime: TypeScript/Node.js. Ao alterar modelo, endpoint ou schema, atualizar este documento.*
