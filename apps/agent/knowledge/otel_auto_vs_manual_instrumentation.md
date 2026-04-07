> **Fonte:** [Artefato público Claude — Auto vs Manual Instrumentation](https://claude.ai/public/artifacts/427d03bd-04f2-4d70-b465-f56449864c9c). Curado para ingestão RAG global (Lumis).

---

# Auto vs Manual Instrumentation Detection

## Lumis Agent Guide · Knowledge Base · v1.0

Propósito RAG: Este documento ensina o agente a distinguir instrumentação automática de manual antes de gerar findings. Um finding de "span ausente" em código com auto-instrumentation ativo é um falso positivo crítico.

Regra cardinal: Detecte o modo de instrumentação PRIMEIRO. Só então avalie gaps. As recomendações diferem radicalmente entre os dois modos.

---

## 1. Por que a distinção importa para o agente

Quando o agente analisa um handler HTTP em Go e não encontra`tracer.Start()` no código, existem dois cenários completamente diferentes:

Cenário A — Auto-instrumentation ativo:

go

```
// Handler sem nenhuma chamada OTel explícita
func (h *Handler) ProcessOrder(w http.ResponseWriter, r *http.Request) {
    order := h.repo.FindOrder(r.Context(), orderID)
    // ... lógica de negócio
}
```

→ O span`HTTP POST /orders` JÁ EXISTE, criado pelo middleware de auto-instrumentation. → O context já está propagado via`r.Context()`. → Reportar "span ausente" aqui é um falso positivo.

Cenário B — Instrumentação manual esperada (sem auto-instrumentation):

go

```
// Mesmo código, mas sem auto-instrumentation configurado
func (h *Handler) ProcessOrder(w http.ResponseWriter, r *http.Request) {
    order := h.repo.FindOrder(r.Context(), orderID)
    // ... lógica de negócio
}
```

→ Nenhum span será criado. Endpoint completamente invisível. → Reportar "span ausente" aqui é um finding crítico legítimo.

O código é idêntico. A diferença está na configuração do SDK e nas dependências.

---

## 2. Sinais de detecção — Auto-instrumentation OTel

### 2.1 Go

Dependências no go.mod que indicam auto-instrumentation:

```
# Instrumentações de biblioteca — cada uma injeta spans automaticamente
go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp        → HTTP server/client
go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc → gRPC
go.opentelemetry.io/contrib/instrumentation/database/sql/otelsql      → database/sql
go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin → Gin
go.opentelemetry.io/contrib/instrumentation/github.com/gorilla/mux/otelmux   → Gorilla Mux
go.opentelemetry.io/contrib/instrumentation/go.mongodb.org/mongo-driver/otelmongo → MongoDB
go.opentelemetry.io/contrib/instrumentation/github.com/aws/aws-sdk-go-v2/otelaws → AWS SDK
```

Padrões de uso no código que confirmam auto-instrumentation:

go

```
// Padrão 1: otelhttp.NewHandler wrapping — span criado automaticamente para CADA request
mux := http.NewServeMux()
handler := otelhttp.NewHandler(mux, "my-service")
http.ListenAndServe(":8080", handler)
// → TODO handler dentro deste mux tem span automático

// Padrão 2: otelgin middleware
r := gin.New()
r.Use(otelgin.Middleware("my-service"))
// → TODOS os endpoints Gin têm span automático

// Padrão 3: otelmux middleware
r := mux.NewRouter()
r.Use(otelmux.Middleware("my-service"))
// → TODOS os endpoints Gorilla têm span automático

// Padrão 4: otelsql — wrap da conexão de banco
db, err := otelsql.Open("postgres", dsn,
    otelsql.WithAttributes(semconv.DBSystemPostgreSQL))
// → TODAS as queries neste db têm span automático

// Padrão 5: otelgrpc interceptors
grpc.NewServer(
    grpc.UnaryInterceptor(otelgrpc.UnaryServerInterceptor()),
    grpc.StreamInterceptor(otelgrpc.StreamServerInterceptor()),
)
// → TODOS os métodos gRPC têm span automático
```

O que o context propagation automático cobre em Go:

Com`otelhttp.NewHandler`:

- O`r.Context()` passado para o handler já contém o span ativo
- Chamadas a`otelsql`,`otelhttp.DefaultClient`, etc. herdam automaticamente
- `r.Context()` propagado para goroutines filhas carrega o trace context

O que NÃO é coberto automaticamente em Go (gaps reais mesmo com auto-instrumentation):

go

```
// ❌ Goroutine sem propagação explícita — trace context PERDIDO
go func() {
    // r.Context() não foi passado — esta goroutine está fora do trace
    result := doHeavyWork()
}()

// ✅ Correto: propagar contexto explicitamente
ctx := r.Context()
go func() {
    result := doHeavyWork(ctx) // ctx carrega o span pai
}()
```

go

```
// ❌ Função de domínio crítica sem span filho — aparece como black box
func (r *OrderRepo) ReserveStock(ctx context.Context, items []Item) error {
    // ctx está correto, mas sem span filho não há visibilidade desta operação
    return r.db.ExecContext(ctx, "UPDATE stock SET reserved = ...")
    // EXCEÇÃO: se db foi wrapped com otelsql, a query tem span automático
}

// ✅ Quando adicionar span filho manual mesmo com auto-instrumentation:
// apenas para operações de domínio críticas que não são I/O puro
func (r *OrderRepo) ReserveStock(ctx context.Context, items []Item) error {
    ctx, span := tracer.Start(ctx, "ReserveStock",
        trace.WithAttributes(attribute.Int("items.count", len(items))))
    defer span.End()
    return r.db.ExecContext(ctx, "UPDATE stock SET reserved = ...")
}
```

### 2.2 Python

Dependências que indicam auto-instrumentation OTel:

```
# opentelemetry-instrumentation-* packages no requirements.txt / pyproject.toml
opentelemetry-instrumentation-fastapi      → FastAPI auto-spans
opentelemetry-instrumentation-django       → Django auto-spans
opentelemetry-instrumentation-flask        → Flask auto-spans
opentelemetry-instrumentation-sqlalchemy   → SQLAlchemy queries
opentelemetry-instrumentation-psycopg2     → PostgreSQL direto
opentelemetry-instrumentation-redis        → Redis commands
opentelemetry-instrumentation-celery       → Celery tasks
opentelemetry-instrumentation-httpx        → httpx client calls
opentelemetry-instrumentation-requests     → requests library
opentelemetry-instrumentation-aio-pika     → RabbitMQ async
opentelemetry-instrumentation-kafka-python → Kafka producer/consumer
```

Padrão de ativação — opentelemetry-instrument CLI:

bash

```
# Quando a aplicação é iniciada assim, TUDO é auto-instrumentado
opentelemetry-instrument \
    --traces_exporter otlp \
    --metrics_exporter otlp \
    uvicorn main:app --host 0.0.0.0 --port 8000
```

Se o Dockerfile ou o Procfile/entrypoint usa`opentelemetry-instrument`, todos os frameworks listados acima têm spans automáticos.

Padrão de ativação — programático:

python

```
# main.py ou app factory — instrumentação aplicada no import
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

FastAPIInstrumentor.instrument_app(app)   # → todos os endpoints FastAPI
SQLAlchemyInstrumentor().instrument()     # → todas as queries SQLAlchemy
RedisInstrumentor().instrument()          # → todos os comandos Redis
```

Context propagation automático em Python async:

python

```
# Com FastAPI + opentelemetry-instrumentation-fastapi:
# O span de request JÁ EXISTE quando o handler é chamado
# O contexto é propagado via contextvars automaticamente

@app.post("/checkout")
async def checkout(request: Request):
    # span "POST /checkout" já está ativo — sem código OTel explícito
    order = await order_service.create(request.state.data)
    # se order_service usa SQLAlchemy instrumentado, a query tem span filho
    return order

# ❌ asyncio.create_task() QUEBRA o contexto — mesmo com auto-instrumentation
async def checkout(request: Request):
    task = asyncio.create_task(notify_fulfillment())  # PERDE o trace context
    # notify_fulfillment roda em contexto vazio — orphan span

# ✅ Correto: copiar contexto explicitamente
from opentelemetry import context
async def checkout(request: Request):
    ctx = context.get_current()
    task = asyncio.create_task(notify_fulfillment(ctx))
```

### 2.3 Java (Spring Boot)

Auto-instrumentation via Java Agent (mais completo de todos):

bash

```
# Quando o JVM inicia com este agente, TUDO é instrumentado via bytecode injection
java -javaagent:/opt/opentelemetry-javaagent.jar \
     -Dotel.service.name=checkout-service \
     -Dotel.traces.exporter=otlp \
     -jar app.jar
```

O Java Agent instrumenta automaticamente:

- Spring MVC / Spring WebFlux (todos os @Controller, @RestController)
- JDBC (todas as queries — qualquer driver)
- Spring Data JPA / Hibernate
- Kafka, RabbitMQ, ActiveMQ
- gRPC, Feign, RestTemplate, WebClient
- Redis (Lettuce, Jedis)
- MongoDB, Elasticsearch

Indicadores no pom.xml / build.gradle:

xml

```
<!-- opentelemetry-spring-boot-starter → programmatic, não agent -->
<dependency>
    <groupId>io.opentelemetry.instrumentation</groupId>
    <artifactId>opentelemetry-spring-boot-starter</artifactId>
</dependency>
```

groovy

```
// build.gradle
implementation 'io.opentelemetry.instrumentation:opentelemetry-spring-boot-starter'
```

Com o Java Agent ativo, código sem spans explícitos está correto:

java

```
// SEM spans explícitos — mas completamente instrumentado pelo agent
@RestController
public class OrderController {
    @PostMapping("/orders")
    public ResponseEntity<Order> createOrder(@RequestBody OrderRequest req) {
        // span "POST /orders" criado automaticamente
        Order order = orderService.create(req);
        // se orderService usa JPA, a query tem span filho automático
        return ResponseEntity.ok(order);
    }
}
```

Gaps reais mesmo com Java Agent:

java

```
// ❌ CompletableFuture sem context propagation — contexto perdido
CompletableFuture.supplyAsync(() -> {
    // roda em thread pool sem o context OTel do thread pai
    return inventoryService.checkStock(items);
});

// ✅ Correto: usar Context.current().wrap()
Context ctx = Context.current();
CompletableFuture.supplyAsync(ctx.wrap(() -> {
    return inventoryService.checkStock(items);
}));
```

### 2.4 Node.js / TypeScript

Auto-instrumentation via @opentelemetry/auto-instrumentations-node:

typescript

```
// CRÍTICO: este arquivo DEVE ser o primeiro import da aplicação
// src/instrumentation.ts (ou tracing.ts)
import { NodeSDK } from '@opentelemetry/sdk-node'
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node'

const sdk = new NodeSDK({
  instrumentations: [
    getNodeAutoInstrumentations() // instrumenta tudo automaticamente
  ],
})
sdk.start()
```

json

```
// package.json — iniciado com --require
{
  "scripts": {
    "start": "node --require ./src/instrumentation.js dist/index.js"
  }
}
```

O que`getNodeAutoInstrumentations()` cobre:

- express, fastify, koa, hapi → spans de HTTP automáticos
- http, https modules → spans de saída automáticos
- pg, mysql2, mongodb → spans de query automáticos
- redis, ioredis → spans de comando automáticos
- grpc → spans automáticos
- aws-sdk → spans automáticos

Context propagation automático em Node:

typescript

```
// Com Express instrumentado:
app.post('/checkout', async (req, res) => {
  // span "POST /checkout" já existe — criado pelo middleware OTel
  // AsyncLocalStorage propaga o context automaticamente em async/await
  const order = await orderService.create(req.body)
  // se orderService usa pg instrumentado, a query tem span filho
  res.json(order)
})

// ❌ setTimeout/setInterval PODE perder contexto dependendo da versão
setTimeout(async () => {
  // pode ou não ter o context — comportamento inconsistente
  await notifyFulfillment(order)
}, 0)

// ✅ Correto: usar context.with() explicitamente
const ctx = context.active()
setTimeout(async () => {
  await context.with(ctx, async () => {
    await notifyFulfillment(order)
  })
}, 0)
```

---

## 3. Sinais de detecção — Auto-instrumentation Datadog

### 3.1 Datadog Agent (dd-trace)

O Datadog usa uma abordagem diferente do OTel: o`dd-trace` faz monkey-patching das bibliotecas no momento do`require`/`import`, sem necessidade de configuração por endpoint.

Indicadores no código/config que confirmam dd-trace ativo:

javascript

```
// Node.js — DEVE ser o primeiro require
require('dd-trace').init({
  service: 'checkout-service',
  env: 'production',
  version: '1.2.3',
})
// → a partir daqui, express/pg/redis/etc são monkey-patched automaticamente
```

python

```
# Python — import ddtrace antes de qualquer outra coisa
import ddtrace
ddtrace.patch_all()  # ou ddtrace.patch(fastapi=True, sqlalchemy=True, redis=True)
# → equivalente ao opentelemetry-instrument
```

go

```
// Go — sem agent automático completo; usa instrumentação explícita com dd-trace/go
// Indicadores: imports de gopkg.in/DataDog/dd-trace-go.v1/...
import (
    "gopkg.in/DataDog/dd-trace-go.v1/contrib/net/http"         // httptrace
    "gopkg.in/DataDog/dd-trace-go.v1/contrib/database/sql"    // sqltrace
    "gopkg.in/DataDog/dd-trace-go.v1/contrib/gin-gonic/gin"   // gintrace
)
```

java

```
# Java — Datadog Java Agent via JVM flag (similar ao OTel Agent)
# Dockerfile ou startup script:
java -javaagent:/opt/dd-java-agent.jar \
     -Ddd.service=checkout-service \
     -Ddd.env=production \
     -jar app.jar
```

Detecção via Dockerfile / docker-compose / Kubernetes:

dockerfile

```
# Datadog Agent sidecar no pod — indica APM ativo
# docker-compose.yml
services:
  datadog-agent:
    image: datadog/agent:latest
    environment:
      - DD_APM_ENABLED=true
      - DD_APM_NON_LOCAL_TRAFFIC=true
```

yaml

```
# Kubernetes — Datadog admission controller (auto-injeção)
annotations:
  admission.datadoghq.com/java-lib.version: "latest"
  # → agent injeta dd-java-agent.jar automaticamente no pod
```

yaml

```
# Helm values — Datadog Cluster Agent com APM
datadog:
  apm:
    enabled: true
    portEnabled: true
```

### 3.2 O que dd-trace cobre automaticamente vs OTel

| Capacidade | OTel Auto-Instrument | dd-trace |
| --- | --- | --- |
| HTTP server spans | via middleware wrapper | monkey-patch automático |
| HTTP client spans | via FetchInstrumentation | monkey-patch automático |
| DB query spans | via library instrumentation | monkey-patch automático |
| Context propagation | via AsyncLocalStorage/contextvars | via AsyncLocalStorage/contextvars |
| Log injection (trace_id) | manual ou via log bridge | automático com ddtrace |
| Goroutine/thread context | MANUAL sempre | MANUAL sempre |
| Custom spans | `tracer.Start()`/`with tracer.start_as_current_span()` | `ddtrace.tracer.StartSpan()` |

Diferença crítica — log injection:

python

```
# Com dd-trace: trace_id e span_id injetados automaticamente nos logs
import logging
import ddtrace.contrib.logging  # este import ativa a injeção automática

logging.basicConfig(
    format='%(asctime)s %(message)s [dd.trace_id=%(dd.trace_id)s dd.span_id=%(dd.span_id)s]'
)
# → todos os logs têm trace_id sem código adicional

# Com OTel: injeção de trace_id em logs requer configuração explícita
# ou uso do log bridge (opentelemetry-instrumentation-logging)
import logging
from opentelemetry.instrumentation.logging import LoggingInstrumentor
LoggingInstrumentor().instrument()
# → adiciona trace_id ao LogRecord automaticamente
```

---

## 4. Regras de decisão para o agente

### 4.1 Algoritmo de detecção de modo

```
PARA CADA arquivo/serviço analisado:

1. VERIFICAR indicadores de auto-instrumentation (em ordem):
   a. go.mod / requirements.txt / package.json / pom.xml / build.gradle
      → presença de pacotes de auto-instrumentation?
   b. Dockerfile / entrypoint / Makefile / helm values
      → uso de opentelemetry-instrument, -javaagent, dd-trace init?
   c. Arquivo de configuração de SDK (tracing.ts, instrumentation.py)
      → NodeSDK.start(), sdk.init(), patch_all()?
   d. Código de bootstrap (main.go, main.py, app.py, index.ts)
      → wrappers de middleware (otelhttp.NewHandler, FastAPIInstrumentor)?

2. CLASSIFICAR o modo:
   → FULL_AUTO:    Java Agent / opentelemetry-instrument CLI / dd-trace patch_all
   → PARTIAL_AUTO: apenas algumas libs instrumentadas (ex: só SQLAlchemy)
   → MANUAL:       sem indicadores de auto-instrumentation

3. APLICAR regras de finding conforme o modo (ver seção 4.2)
```

### 4.2 Regras de finding por modo de instrumentação

Modo FULL_AUTO (Java Agent, opentelemetry-instrument CLI):

```
NÃO REPORTAR como gap:
  ✗ Ausência de span em HTTP handlers/controllers
  ✗ Ausência de span em queries de banco de dados
  ✗ Ausência de span em chamadas HTTP de saída (client)
  ✗ Ausência de span em operações Redis, Kafka, gRPC
  ✗ Ausência de trace_id em logs (se log bridge ativo)

REPORTAR como gap (gaps reais mesmo com FULL_AUTO):
  ✓ Goroutine (Go) sem context propagation explícito
  ✓ asyncio.create_task() (Python) sem context.copy()
  ✓ CompletableFuture (Java) sem Context.current().wrap()
  ✓ setTimeout/setInterval (Node) sem context.with()
  ✓ Funções de domínio críticas (afetam $$$) sem span filho manual
  ✓ Error paths sem span.RecordError() mesmo que o span pai exista
  ✓ Ausência de atributos semânticos customizados em spans críticos
  ✓ Sampling não configurado (100% default ainda é problema)
  ✓ Health/liveness endpoints sendo tracejados (geram ruído)
```

Modo PARTIAL_AUTO (algumas libs instrumentadas):

```
NÃO REPORTAR para libs com instrumentação ativa:
  ✗ Ausência de span em chamadas às libs instrumentadas

REPORTAR para libs SEM instrumentação:
  ✓ HTTP handler sem span se o framework não está instrumentado
  ✓ Chamada de banco sem span se o driver não está instrumentado

SEMPRE REPORTAR (independente de libs):
  ✓ Todos os gaps de context propagation (goroutines, async, threads)
  ✓ Error paths sem captura
  ✓ Sampling não configurado
```

Modo MANUAL (sem auto-instrumentation):

```
REPORTAR tudo que está ausente:
  ✓ HTTP handler sem span de entrada
  ✓ DB call sem span filho
  ✓ HTTP client sem span + traceparent inject
  ✓ Kafka/RabbitMQ produce sem W3C context nos headers
  ✓ Error paths sem RecordError()
  ✓ Funções de I/O sem span
  ✓ Ausência de trace_id em logs
  ✓ Sampling não configurado
  ✓ Tags obrigatórias ausentes
```

### 4.3 Template de finding contextualizado por modo

Finding correto para FULL_AUTO:

markdown

```
## [TRACES · ATENÇÃO] Context perdido em goroutine — checkout-api/payment.go:203

**Modo de instrumentação detectado**: OTel Auto (otelhttp.NewHandler ativo)

O span HTTP do handler é criado automaticamente pelo otelhttp middleware.
Porém, a goroutine lançada na linha 203 não recebe o `ctx` do handler,
criando um span órfão desconectado do trace principal.

**Arquivo**: payment.go:203
**Padrão detectado**: `go func() { ... }()` sem context propagation

**Sugestão**:
\`\`\`go
// Antes (linha 203) — goroutine perde o trace context
go func() {
    notifyFulfillment(order)
}()

// Depois — trace context propagado corretamente
ctx := r.Context() // ctx do handler já tem o span do otelhttp
go func() {
    notifyFulfillment(ctx, order)
}()
\`\`\`

**Impacto**: spans de notifyFulfillment aparecem como root spans no Datadog/Jaeger
em vez de filhos do trace do checkout, impossibilitando correlação.
```

Finding correto para MANUAL (mesmo padrão de código):

markdown

```
## [TRACES · CRÍTICO] HTTP handler sem instrumentação — checkout-api/payment.go

**Modo de instrumentação detectado**: Manual (sem otelhttp ou dd-trace detectados)

O handler ProcessPayment não possui span de entrada. Toda a operação de pagamento
é invisível no trace — latência, erros e contexto de negócio não são capturados.

**Arquivo**: payment.go:45
**Padrão detectado**: `http.HandlerFunc` sem `tracer.Start()`

**Sugestão**:
\`\`\`go
func (h *Handler) ProcessPayment(w http.ResponseWriter, r *http.Request) {
    ctx, span := tracer.Start(r.Context(), "ProcessPayment",
        trace.WithAttributes(
            attribute.String("payment.method", r.Header.Get("X-Payment-Method")),
        ))
    defer span.End()

    // ... lógica existente usando ctx
}
\`\`\`
```

---

## 5. Recomendações de modo por contexto

### 5.1 Quando recomendar Auto-instrumentation

Recomendar auto-instrumentation quando:

- Time novo em observabilidade: zero configuração para ter traces básicos
- Cobertura ampla necessária: precisa ver TUDO sem inventariar o código
- Migração incremental: adiciona observabilidade sem tocar em código legado
- Microserviços com muitos endpoints: custo de instrumentar manualmente é alto
- Linguagem com agent maduro: Java (OTel Agent), Python (opentelemetry-instrument)

Limitações que o agente deve comunicar:

```
Auto-instrumentation tem custo de overhead:
  - Java Agent: +5-15% de uso de CPU no startup, +10-30ms de latência por request
    em aplicações com muitas integrações
  - Python opentelemetry-instrument: overhead de ~2-5% em throughput
  - Node auto-instrumentations: overhead de ~1-3% dependendo do número de libs
  - Go: sem agent automático completo — cada lib requer wrapper explícito

Spans gerados podem incluir ruído:
  - Health check endpoints tracejados por padrão
  - Queries internas de framework (ex: Spring Actuator) visíveis no trace
  - Necessário configurar ignored_urls/ignored_resources para limpar
```

### 5.2 Quando recomendar Instrumentação Manual

Recomendar instrumentação manual quando:

- Performance é crítica: APIs de baixa latência (<10ms) onde 2-5% importa
- Controle de custo de APM: pagar por span — auto-instrumentation gera 10x mais spans
- Semântica de negócio: o time quer observar operações de domínio, não I/O genérico
- Go em produção: auto-instrumentation em Go requer wrapper por lib — custo similar ao manual
- Refinamento após auto-instrumentation: começou com auto, quer reduzir ruído e custo

Vantagens específicas da instrumentação manual:

```
1. Controle de cardinality: você decide quais atributos adicionar nos spans
   Auto: adiciona muitos atributos por padrão (alguns de alto custo de cardinalidade)
   Manual: você escolhe exatamente o que é relevante

2. Sem spans de ruído: formatPayload(), validateSchema() não viram spans
   Auto: qualquer chamada instrumentada vira span automaticamente

3. Atributos de negócio: span com order.value, customer.tier, payment.method
   Auto: gera spans técnicos (HTTP 200, SQL SELECT) sem contexto de negócio

4. Sampling preciso: você sabe exatamente o que está sendo amostrado
   Auto: sampling aplicado depois de spans já criados — custo de criação sempre existe
```

### 5.3 Modo híbrido (recomendação padrão para times maduros)

O modo mais eficiente combina os dois:

```
Camada 1 — Auto-instrumentation para I/O de infraestrutura:
  → HTTP, DB queries, Redis, Kafka, gRPC — spans gerados automaticamente
  → Garante visibilidade de latência de infraestrutura sem código

Camada 2 — Manual para operações de domínio críticas:
  → processPayment(), reserveStock(), applyDiscount() — spans explícitos
  → Atributos de negócio: order.value, user.tier, discount.code
  → Apenas para funções que afetam $$$, estoque, ou dado crítico

Camada 3 — Sampling agressivo para controlar custo:
  → 100% para erros e transações críticas (checkout, payment)
  → 10% para fluxos de sucesso
  → 1% para health checks e operações de baixo risco
  → Filter: ignorar /health, /ready, /metrics completamente
```

---

## 6. Detecção de IaC — auto-instrumentation configurado na infraestrutura

### 6.1 Kubernetes — Datadog Admission Controller

yaml

```
# Este annotation no Deployment indica auto-instrumentation Datadog via admission controller
# O agent injeta a lib automaticamente no pod sem alterar o código
metadata:
  annotations:
    admission.datadoghq.com/java-lib.version: "latest"
    admission.datadoghq.com/python-lib.version: "latest"
    admission.datadoghq.com/js-lib.version: "latest"
    admission.datadoghq.com/dotnet-lib.version: "latest"
```

Quando o agente encontrar esses annotations em Helm/K8s manifests: → O serviço tem auto-instrumentation DD ativo → Aplicar regras de modo FULL_AUTO para o serviço correspondente

### 6.2 Kubernetes — OTel Operator

yaml

```
# OTel Operator com auto-instrumentation annotation
metadata:
  annotations:
    instrumentation.opentelemetry.io/inject-java: "true"
    instrumentation.opentelemetry.io/inject-python: "true"
    instrumentation.opentelemetry.io/inject-nodejs: "true"
```

Quando o agente encontrar esses annotations: → O serviço tem auto-instrumentation OTel via operator → Aplicar regras de modo FULL_AUTO

### 6.3 Helm / Docker — variáveis de ambiente indicativas

yaml

```
# Variáveis de ambiente que confirmam auto-instrumentation ativo
env:
  - name: OTEL_TRACES_EXPORTER        # OTel configurado via env
    value: otlp
  - name: OTEL_SERVICE_NAME
    value: checkout-service
  - name: JAVA_TOOL_OPTIONS           # Java agent injetado via env
    value: "-javaagent:/opt/opentelemetry-javaagent.jar"
  - name: DD_TRACE_ENABLED            # Datadog APM via env
    value: "true"
  - name: DD_SERVICE
    value: checkout-service
  - name: NODE_OPTIONS                # Node.js auto-instrumentation
    value: "--require /app/src/instrumentation.js"
```

---

## 7. Antipadrões que confundem a detecção

### 7.1 Auto-instrumentation configurado mas não aplicado

python

```
# requirements.txt tem o pacote MAS o código não chama .instrument()
opentelemetry-instrumentation-fastapi==0.45b0

# app.py
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# FastAPIInstrumentor.instrument_app(app)  ← COMENTADO ou AUSENTE
```

→ Pacote presente não significa instrumentação ativa. → Verificar se a chamada de ativação existe E não está comentada.

### 7.2 opentelemetry-instrument no dev mas não em prod

dockerfile

```
# Dockerfile de desenvolvimento
CMD ["opentelemetry-instrument", "uvicorn", "main:app"]

# Dockerfile de produção (diferente)
CMD ["uvicorn", "main:app"]  # sem opentelemetry-instrument
```

→ Verificar qual Dockerfile é usado em produção. → Se ambos existem, inspecionar qual está referenciado no Helm values.

### 7.3 dd-trace init presente mas desabilitado por flag

javascript

```
require('dd-trace').init({
  enabled: process.env.DD_TRACE_ENABLED !== 'false', // desabilitado em alguns envs
  service: 'checkout-service',
})
```

→ Verificar variáveis de ambiente para confirmar se está realmente ativo.

---

## 8. Resumo de sinais para detecção rápida

| Sinal encontrado | Modo inferido | Confiança |
| --- | --- | --- |
| `-javaagent:opentelemetry-javaagent.jar` no Dockerfile/CMD | FULL_AUTO (OTel) | Alta |
| `-javaagent:dd-java-agent.jar` no Dockerfile/CMD | FULL_AUTO (DD) | Alta |
| `opentelemetry-instrument` no CMD/entrypoint | FULL_AUTO (OTel) | Alta |
| `ddtrace.patch_all()` ou`ddtrace-run` | FULL_AUTO (DD) | Alta |
| `admission.datadoghq.com/java-lib.version` annotation | FULL_AUTO (DD) | Alta |
| `instrumentation.opentelemetry.io/inject-java` annotation | FULL_AUTO (OTel) | Alta |
| `otelhttp.NewHandler`/`otelgin.Middleware` no código | PARTIAL_AUTO (OTel) | Alta |
| `FastAPIInstrumentor.instrument_app()` no código | PARTIAL_AUTO (OTel) | Alta |
| `require('dd-trace').init()` no primeiro arquivo | FULL_AUTO (DD) | Alta |
| `DD_TRACE_ENABLED=true` env var | FULL_AUTO (DD) | Média |
| `JAVA_TOOL_OPTIONS` com javaagent no env | FULL_AUTO | Alta |
| `NODE_OPTIONS` com`--require` tracing file | FULL_AUTO (OTel) | Alta |
| Apenas`opentelemetry-sdk` sem`instrumentation-*` | MANUAL | Alta |
| Nenhum sinal OTel ou DD detectado | MANUAL | Média |

---

## 9. Impacto no scoring de eficiência

O score de eficiência do Lumis deve ser ajustado conforme o modo detectado:

COST score — ajuste por modo:

- FULL_AUTO gera mais spans por padrão → penalizar se sem sampling configurado
- MANUAL gera só o que foi instrumentado → não penalizar pela ausência de spans automáticos
- Híbrido bem configurado → score máximo de eficiência de custo

PIPELINE score — ajuste por modo:

- FULL_AUTO sem ignored_urls → penalizar (health checks no trace = custo desnecessário)
- MANUAL sem batch processor → penalizar (cada span é uma request HTTP)
- FULL_AUTO com sampling tail-based → bonus de eficiência

SNR score — ajuste por modo:

- FULL_AUTO com todos os spans visíveis → verificar se há spans de ruído (formatPayload, validators)
- MANUAL → verificar se há gaps em error paths e I/O crítico
- Híbrido → verificar se a separação auto/manual está bem definida

---
