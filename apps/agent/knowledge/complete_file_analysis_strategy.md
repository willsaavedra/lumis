> **Fonte:** Spec interna — Complete File Analysis Strategy v1.0

---

# Complete File Analysis Strategy

## Horion Agent · analyze_coverage_node + analyze_efficiency_node · v1.0

Propósito RAG: Este documento define como o agente garante análise completa
de todos os arquivos selecionados, respeitando limites de contexto LLM,
sem sacrificar qualidade nem cobertura.

Invariante central: Todo arquivo que passou pelo pre_triage_node com
score >= 1 DEVE aparecer no execution summary como analyzed: true ou
analyzed: false, reason: X. Nunca pode silenciosamente desaparecer.

---

## 1. Princípios

- Nunca truncar arquivos silenciosamente — usar chunking semântico se necessário
- Nunca parar quando o budget se esgota — a análise deve ser completa
- Analisar em batches que cabem no context window do modelo
- Agrupar arquivos do mesmo domínio no mesmo batch para coesão semântica
- Injetar call graph compacto como contexto compartilhado em todos os batches
- Executar batches em paralelo respeitando rate limits
- Retry automático com batch splitting para falhas
- Validar que o output do LLM cobre todos os arquivos do batch

## 2. Batch sizing por modelo

- Claude Sonnet 4 (200k ctx): ~145k tokens usáveis para arquivos
- Modelo próprio 128k: ~91k tokens usáveis
- Modelo próprio 32k: ~17k tokens usáveis
- Overhead fixo: system prompt (~4k) + call graph (~6k) + RAG (~3k)
- Output reservado: 6k tokens
- Margem de segurança: 20%

## 3. File chunking

Arquivos que excedem o budget de um batch são divididos em limites de
função (regex-based). Cada chunk inclui o header do arquivo (imports) e
assinaturas das funções adjacentes como contexto.

## 4. Completeness manifest

Todo arquivo é rastreado desde a triagem até o relatório final. O manifest
garante que nenhum arquivo é silenciosamente descartado.

## 5. Antipadrões

- Truncação silenciosa de conteúdo de arquivo
- Early exit por custo antes de completar a análise
- Análise sem contexto cross-file (call graph)
- Batches grandes demais com output truncado
