> **Fonte:** [Artefato público Claude — File Triage Guide](https://claude.ai/public/artifacts/40458079-9e7e-496f-a831-3f4e955425bc). Curado para ingestão RAG (Horion).

---

# File Triage Guide — Observability Analysis

## Horion Agent · pre_triage_node · Knowledge Base · v1.0

Propósito RAG: Este documento guia o `pre_triage_node` na seleção de arquivos relevantes para análise de observabilidade. O objetivo é eliminar ruído antes de qualquer chamada LLM cara, identificando quais arquivos têm código de aplicação real vs configuração, build, assets e boilerplate.

Regra de ouro: Priorize arquivos onde código de negócio executa. Ignore tudo que apenas descreve como o código é construído ou empacotado.

---

## 1. Princípios gerais de triagem

### 1.1 O que SEMPRE vale analisar

Qualquer arquivo que contenha ao menos um dos seguintes padrões é candidato à análise de observabilidade:

- Definição de HTTP handler / endpoint / route
- Conexão com banco de dados (SQL, NoSQL, cache)
- Chamada de API externa (HTTP client, gRPC client)
- Produção ou consumo de mensagens (Kafka, RabbitMQ, SQS, Pub/Sub)
- Processamento de jobs assíncronos / workers / tasks
- Lógica de negócio crítica (pagamento, estoque, autenticação, pedido)
- Inicialização do servidor / bootstrap da aplicação
- Middleware de autenticação / autorização
- Tratamento de erros global / error boundary

### 1.2 O que NUNCA vale analisar

Descarte imediato independente da linguagem — score 0:

```
# Gerenciamento de dependências
package.json, package-lock.json, yarn.lock, pnpm-lock.yaml
go.sum, poetry.lock, Pipfile.lock, requirements.txt, Gemfile.lock
pom.xml (apenas dependências), build.gradle (apenas dependências)
*.lock, *.sum

# Build e compilação
Makefile, webpack.config.js, vite.config.ts, rollup.config.js, babel.config.js
tsconfig.json, .babelrc, .swcrc, jest.config.ts, vitest.config.ts
*.min.js, *.bundle.js, dist/**, build/**, out/**, target/**

# Assets e estáticos
*.css, *.scss, *.sass, *.less, *.styl
*.svg, *.png, *.jpg, *.gif, *.ico, *.woff, *.ttf, *.eot
*.html (exceto templates server-side com lógica)
public/**, static/**, assets/**

# Configuração de ambiente
.env, .env.*, .env.local, .env.example

# Testes
**/*.test.ts, **/*.spec.ts, **/*.test.go, **/*_test.go
**/*.test.py, **/*_spec.rb, **/*.test.java
__tests__/**, test/**, tests/**, spec/**

# Documentação
*.md, *.mdx, *.rst, *.txt, CHANGELOG, LICENSE, README*

# Linting e formatação
.eslintrc*, .prettierrc*, .editorconfig, .gitignore, .gitattributes
pylintrc, .flake8, mypy.ini, pyproject.toml

# CI/CD
.github/workflows/**, .gitlab-ci.yml, .circleci/**, Jenkinsfile

# Gerados automaticamente
*_generated.go, *.pb.go, *.pb.py, *_pb2.py, *_grpc.py
openapi.yaml, swagger.json
```

### 1.3 Tratamento de arquivos de teste

Score 0: testes unitários, snapshots, fixtures, mocks
Score 1 (baixa prioridade): testes de integração com banco real, testes de contrato de API

---

## 2. Nomes de arquivo que SEMPRE indicam score 2

Independente da extensão ou linguagem:

```
server.*         → bootstrap do servidor HTTP
app.*            → factory da aplicação
main.*           → entry point do programa
router.*         → definição de rotas
routes.*         → idem
handler.*        → HTTP handler
controller.*     → MVC controller
service.*        → camada de serviço
repository.*     → acesso a dados
consumer.*       → consumidor de mensagem (Kafka, RabbitMQ, SQS)
producer.*       → produtor de mensagem
worker.*         → processador de job assíncrono
scheduler.*      → agendador de tarefas
middleware.*     → middleware HTTP
auth.*           → autenticação
payment.*        → pagamento (CRÍTICO)
order.*          → pedido (CRÍTICO)
inventory.*      → estoque (CRÍTICO)
checkout.*       → checkout (CRÍTICO)
transaction.*    → transação financeira (CRÍTICO)
```

## 3. Nomes de arquivo que SEMPRE indicam score 0

```
package.json, package-lock.json, yarn.lock, pnpm-lock.yaml
go.sum, go.mod, requirements.txt, Pipfile.lock, poetry.lock
Makefile, Dockerfile, docker-compose.yml
.env, .env.*, .envrc
tsconfig.json, jsconfig.json
webpack.config.*, vite.config.*, rollup.config.*
jest.config.*, vitest.config.*
.eslintrc.*, .prettierrc.*
*.min.js, *.bundle.js
CHANGELOG, LICENSE, README*
```

---

## 4. Score por extensão de arquivo

| Extensão | Score padrão | Condições de override |
|---|---|---|
| `.go` | 1 | Score 2 se nome contiver: handler, service, repo, consumer, producer, server, main |
| `.py` | 1 | Score 2 se nome contiver: view, service, task, consumer, handler, router |
| `.java` | 1 | Score 2 se nome terminar em: Controller, Service, Repository, Consumer, Producer, Handler |
| `.ts` | 1 | Score 2 se nome contiver: controller, service, router, handler, worker, consumer, guard |
| `.js` | 0 | Score 2 apenas se for server.js, app.js ou contiver .listen() |
| `.tf` | 1 | Score 2 se contiver recursos de compute, messaging, ou banco de dados |
| `values.yaml` | 2 | Sempre score 2 em contexto Helm |
| `deployment.yaml` | 2 | Sempre score 2 em contexto K8s/Helm |
| `.json` | 0 | Nunca analisar para observabilidade |
| `.lock` | 0 | Sempre descartar |
| `.sum` | 0 | Sempre descartar |
| `.md` | 0 | Sempre descartar |
| `.env` | 0 | Sempre descartar |
| `.css`,`.scss` | 0 | Sempre descartar |
| `*.test.*`,`*_test.*`,`*spec*` | 0 | Score 1 apenas se for teste de integração com I/O real |

---

## 5. Heurísticas de conteúdo (quando o nome não é suficiente)

Quando o nome do arquivo for ambíguo (ex: index.ts, utils.py, helpers.go), use o conteúdo:

### Indicadores de score 2 no conteúdo

```
Go:       "func main()", "http.HandleFunc", "gin.New()", "chi.NewRouter()", "grpc.NewServer()",
          "kafka.NewConsumer()", "sql.Open()", "gorm.Open()", "pgx.Connect()"

Python:   "@app.route", "@router.get", "@router.post", "app = FastAPI()", "app = Flask()",
          "@celery.task", "kafka.KafkaConsumer", "sqlalchemy.create_engine"

Java:     "@RestController", "@Controller", "@Service", "@Repository",
          "@KafkaListener", "@RabbitListener", "@Scheduled", "@Aspect"

TS/JS:    "express()", "fastify()", ".listen(", "createServer(",
          "app.get(", "router.get(", "@Controller(", "@Injectable(",
          "new Kafka(", "new Worker(", "Queue.process("
```

### Indicadores de score 0 no conteúdo

```
export * from './...'     (barrel re-exports)
export { X } from './...'
module.exports = require('./...')
interface UserDto { ... } (só tipos)
type ResponsePayload = { ... }
```

---

## 6. Regras de prioridade para budget limitado

Quando o orçamento de análise é restrito, priorize nesta ordem:

1. Arquivos com nomes de domínio crítico: payment*, order*, checkout*, transaction*, auth*
2. Entry points e routers: main.*, server.*, app.*, router.*, routes.*
3. Consumers de mensagem: *consumer*, *worker*, *job*
4. Repositórios de banco de dados: *repository*, *repo*, *store*, *dao*
5. Clientes externos: *client*, *gateway*, *adapter*
6. Handlers e controllers: *handler*, *controller*
7. Serviços de domínio: *service*, *usecase*
8. IaC (se incluído): deployment.yaml, values.yaml, *lambda*.tf, *sqs*.tf
9. Arquivos de utilidade relevantes: middleware.*, interceptor.*, filter.*

---

## 7. Padrões específicos por linguagem

### Go: alta prioridade
main.go, cmd/*/main.go, server.go, router.go, *_handler.go, *_service.go,
*_repository.go, *_consumer.go, *_producer.go, middleware.go, worker.go

### Python: alta prioridade
main.py, app.py, *_router.py, views.py, *_service.py, *_repository.py,
tasks.py, *_consumer.py, middleware.py, auth.py, dependencies.py

### Java: alta prioridade
*Controller.java, *Service.java, *Repository.java, Application.java,
*Consumer.java, *Producer.java, *Filter.java, *Interceptor.java

### TypeScript/Node: alta prioridade
server.ts, app.ts, *.controller.ts, *.service.ts, *.guard.ts,
*.interceptor.ts, *.filter.ts, pages/api/**, app/api/**/route.ts

### Terraform: alta prioridade
*lambda*.tf, *ecs*.tf, *sqs*.tf, *rds*.tf, *redis*.tf, *alarm*.tf

### Helm/K8s: alta prioridade
templates/deployment.yaml, values.yaml, templates/cronjob.yaml
