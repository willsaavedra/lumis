"""Node 2: Pre-triage — classify file relevance using knowledge-base heuristics + optional LLM."""
from __future__ import annotations

import json
import os
import re

import structlog

from apps.agent.nodes.base import publish_progress, publish_thought, publish_file_status
from apps.agent.schemas import AgentState, ChangedFile

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Heuristic tables derived from knowledge/file_triage_guide.md
# ---------------------------------------------------------------------------

# Exact filenames that are ALWAYS score 0 (discard)
_ALWAYS_DISCARD_NAMES = frozenset({
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "go.sum", "go.mod", "requirements.txt", "pipfile.lock", "poetry.lock",
    "gemfile.lock", "makefile", "dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "tsconfig.json", "jsconfig.json",
    ".babelrc", ".swcrc", ".eslintrc", ".prettierrc", ".editorconfig",
    ".gitignore", ".gitattributes", ".npmrc", ".yarnrc", ".envrc",
    "pylintrc", ".flake8", "mypy.ini", "changelog", "license",
    ".helmignore", "chart.lock", "cdk.json", "cdk.context.json",
    "conftest.py", "setup.py", "setup.cfg",
})

# Filename prefixes that are always score 0
_ALWAYS_DISCARD_PREFIXES = ("readme", ".env")

# File extensions that are ALWAYS score 0
_ALWAYS_DISCARD_EXTS = frozenset({
    ".md", ".mdx", ".rst", ".txt", ".lock", ".sum",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
    ".css", ".scss", ".sass", ".less", ".styl",
    ".min.js", ".bundle.js",
    ".pyc", ".class",
})

# Path segments that force score 0
_ALWAYS_DISCARD_SEGMENTS = (
    "node_modules/", "vendor/", "dist/", "build/", "out/", "target/",
    "__pycache__/", ".next/", ".nuxt/", ".venv/", "venv/",
    "public/", "static/", "assets/",
    "docs/", "documentation/",
    ".github/workflows/", ".circleci/", ".gitlab-ci",
    "__tests__/", "__mocks__/", "fixtures/", "factories/",
)

# Filename glob-style patterns for score 0
_DISCARD_NAME_PATTERNS = re.compile(
    r"(?:"
    r"webpack\.config|vite\.config|rollup\.config|babel\.config|esbuild\.config"
    r"|jest\.config|vitest\.config"
    r"|\.eslintrc|\.prettierrc"
    r"|_generated\.|\.pb\.|_pb2\.|_pb2_grpc\.|_grpc\."
    r"|_string\.go"      # go generate Stringer
    r"|_mock\.|_mocks\.|mock_"
    r"|\.d\.ts$"
    r")", re.IGNORECASE,
)

# Test file patterns — score 0 by default
_TEST_PATTERN = re.compile(
    r"(?:_test\.|\.test\.|_spec\.|\.spec\.|/tests?/|/spec/)", re.IGNORECASE,
)

# Migration directories — score 0
_MIGRATION_PATTERN = re.compile(r"/migrations?/", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Score 2 — filenames that universally signal high relevance
# ---------------------------------------------------------------------------
_SCORE2_STEMS = frozenset({
    "server", "app", "main", "router", "routes",
    "handler", "handlers", "controller", "controllers",
    "service", "services", "repository", "repo",
    "consumer", "producer", "worker", "scheduler",
    "middleware", "auth", "authentication", "authorization",
    "payment", "order", "inventory", "checkout", "transaction",
})

# Name substrings that bump any source file to score 2
_SCORE2_SUBSTRINGS = (
    "handler", "controller", "service", "repository", "repo",
    "consumer", "producer", "worker", "middleware",
    "usecase", "use_case", "use-case",
    "client", "gateway", "adapter",
    "interceptor", "guard", "filter",
    "scheduler", "cron",
)

# Language-specific name patterns for score 2
_SCORE2_LANG_PATTERNS: dict[str, re.Pattern] = {
    "go": re.compile(
        r"(?:_handler|_service|_repository|_repo|_consumer|_producer"
        r"|_worker|_middleware|_interceptor|_client|_store|_job|_task"
        r"|_db|_grpc_server)\.go$", re.IGNORECASE,
    ),
    "python": re.compile(
        r"(?:_router|_routes|_service|_repository|_consumer|_producer"
        r"|_handler|_task|_worker|_middleware|_hook|_auth|_client"
        r"|_dao|_job|_view|_viewset|_signal|_blueprint)\.py$", re.IGNORECASE,
    ),
    "java": re.compile(
        r"(?:Controller|Service|ServiceImpl|Repository|RepositoryImpl"
        r"|Consumer|Producer|Publisher|Handler|Filter|Interceptor|Aspect"
        r"|ExceptionHandler|Configuration|Scheduler|Gateway|Dao|DaoImpl"
        r"|Application)\.java$",
    ),
    "typescript": re.compile(
        r"(?:\.controller|\.service|\.guard|\.interceptor|\.filter"
        r"|\.module|\.gateway|\.pipe)\.ts$", re.IGNORECASE,
    ),
}

# K8s / Helm files that are always score 2
_K8S_SCORE2 = re.compile(
    r"(?:deployment|statefulset|daemonset|cronjob|job)\.ya?ml$", re.IGNORECASE,
)
_HELM_VALUES = re.compile(r"values(?:[.-]\w+)?\.ya?ml$", re.IGNORECASE)

# Terraform patterns for score 2
_TF_SCORE2 = re.compile(
    r"(?:lambda|ecs|fargate|eks|gke|sqs|sns|kafka|pubsub|eventbridge"
    r"|rds|aurora|dynamodb|redis|elasticache|alb|nlb|elb|apigateway"
    r"|alarm|monitor|dashboard|compute|services|application"
    r"|messaging|queues|events|databases|monitoring|alerting|observability).*\.tf$",
    re.IGNORECASE,
)

# Extensions that qualify as source code (eligible for score 1+)
_SOURCE_EXTENSIONS = frozenset({".go", ".py", ".java", ".ts", ".js", ".tf"})


def _quick_classify(file_path: str) -> int:
    """
    Knowledge-base-driven heuristic classification.

    Returns 0 (discard), 1 (ambiguous — LLM may reclassify), or 2 (high relevance).
    Eliminates most noise without any LLM call.
    """
    lower = file_path.lower()
    basename = os.path.basename(lower)
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename

    # --- Score 0 checks (cheapest first) ---

    if basename in _ALWAYS_DISCARD_NAMES:
        return 0

    for prefix in _ALWAYS_DISCARD_PREFIXES:
        if basename.startswith(prefix):
            return 0

    for ext in _ALWAYS_DISCARD_EXTS:
        if lower.endswith(ext):
            return 0

    for seg in _ALWAYS_DISCARD_SEGMENTS:
        if seg in lower:
            return 0

    if _DISCARD_NAME_PATTERNS.search(basename):
        return 0

    if _TEST_PATTERN.search(lower):
        return 0

    if _MIGRATION_PATTERN.search(lower):
        return 0

    # --- Score 2 checks ---

    # Universal high-relevance stems
    if stem in _SCORE2_STEMS:
        return 2

    # K8s / Helm
    if _K8S_SCORE2.search(basename):
        return 2
    if _HELM_VALUES.search(basename):
        return 2

    # Terraform resource patterns
    if lower.endswith(".tf") and _TF_SCORE2.search(basename):
        return 2

    # Language-specific naming conventions
    lang = _detect_language(file_path)
    if lang and lang in _SCORE2_LANG_PATTERNS:
        if _SCORE2_LANG_PATTERNS[lang].search(basename):
            return 2

    # Generic substring match for any source file
    ext = os.path.splitext(lower)[1]
    if ext in _SOURCE_EXTENSIONS:
        for sub in _SCORE2_SUBSTRINGS:
            if sub in lower:
                return 2

    # Critical business domain keywords in the path
    for domain in ("payment", "order", "checkout", "transaction", "inventory", "billing"):
        if domain in lower and ext in _SOURCE_EXTENSIONS:
            return 2

    # --- Score 1 (ambiguous — may be promoted by LLM or content scan) ---
    if ext in _SOURCE_EXTENSIONS:
        return 1

    # Terraform files not matched above
    if lower.endswith(".tf"):
        return 1

    # Everything else is noise
    return 0


# Content-based indicators (from knowledge/file_triage_guide.md §5 + §11)
_CONTENT_SCORE2_PATTERNS = re.compile(
    r"(?:"
    # Go
    r"func main\(\)"
    r"|http\.HandleFunc|http\.Handle|gin\.New\(\)|chi\.NewRouter\(\)"
    r"|grpc\.NewServer\(\)|grpc\.Dial\(\)"
    r"|kafka\.NewConsumer|kafka\.NewProducer|sarama\.NewConsumer"
    r"|sql\.Open\(\)|gorm\.Open\(\)|pgx\.Connect"
    # Python
    r"|@app\.route|@router\.\w+|app\s*=\s*FastAPI\(\)|app\s*=\s*Flask\(\)"
    r"|@celery\.task|@app\.task"
    r"|kafka\.KafkaConsumer|kafka\.KafkaProducer"
    r"|sqlalchemy\.create_engine"
    # Java
    r"|@RestController|@Controller|@Service|@Repository"
    r"|@KafkaListener|@RabbitListener|@SqsListener"
    r"|@Scheduled|@Aspect"
    # TypeScript / JavaScript
    r"|express\(\)|fastify\(\)|new NestFactory"
    r"|\.listen\(|createServer\("
    r"|app\.get\(|app\.post\(|router\.get\(|router\.post\("
    r"|@Controller\(|@Injectable\(|@EventPattern\("
    r"|new Kafka\(|new Worker\(|Queue\.process\("
    r")",
)

_CONTENT_SCORE0_PATTERNS = re.compile(
    r"^(?:\s*(?:"
    r"export\s+\*\s+from"
    r"|export\s*\{[^}]*\}\s*from"
    r"|module\.exports\s*=\s*require"
    r"|export\s+(?:type|interface)\s"
    r"|(?:type|interface)\s+\w+\s*(?:=|\{)"
    r")\s*.*\n?)+$",
    re.MULTILINE,
)


def _content_heuristic(head: str, file_path: str) -> int:
    """
    Peek at file content to resolve ambiguous (score 1) files.
    Returns 0, 1, or 2.
    """
    if _CONTENT_SCORE2_PATTERNS.search(head):
        return 2

    stripped = head.strip()
    if not stripped:
        return 0

    lines = stripped.splitlines()
    non_empty = [l.strip() for l in lines if l.strip() and not l.strip().startswith("//") and not l.strip().startswith("#")]
    if not non_empty:
        return 0

    # Barrel files: all lines are re-exports
    re_export_count = sum(
        1 for l in non_empty
        if l.startswith("export ") and " from " in l
        or l.startswith("module.exports")
    )
    if re_export_count > 0 and re_export_count >= len(non_empty) * 0.8:
        return 0

    return 1


def _detect_language(file_path: str) -> str | None:
    ext_map = {
        ".go": "go",
        ".py": "python",
        ".java": "java",
        ".ts": "typescript",
        ".js": "javascript",
        ".tf": "terraform",
    }
    for ext, lang in ext_map.items():
        if file_path.endswith(ext):
            return lang
    return None


# Per-type file caps and minimum relevance score to load content
_TYPE_CONFIG: dict[str, dict] = {
    # Quick: only user-selected paths (API requires scope); expand dirs up to cap
    "quick":      {"file_cap": 250, "content_min_score": 2, "llm_classify": False},
    "full":       {"file_cap": 150, "content_min_score": 1, "llm_classify": True},
    # Deep codebase scan — high cap; worker walks src-like trees first
    "repository": {"file_cap": 8000, "content_min_score": 1, "llm_classify": True},
}

# Top-level dirs to walk first for repository-depth analysis (instrumentation lives here)
_PRIORITY_ROOT_DIRS = frozenset({
    "src", "lib", "pkg", "app", "internal", "cmd", "services", "packages",
    "server", "api", "backend", "handlers", "middleware", "components",
})

_SKIP_SEGMENTS = (".git", "__pycache__", "node_modules", "vendor/", "dist/", "build/", ".venv", "venv/")


def _path_should_skip(rel_posix: str) -> bool:
    lower = rel_posix.lower()
    return any(seg in lower for seg in _SKIP_SEGMENTS)


def _expand_repo_roots(repo_root, roots: list[str], *, max_files: int) -> list[str]:
    """
    Expand a list of file paths and/or directory roots to a flat list of file paths
    relative to the repository root (posix).
    """
    from pathlib import Path

    repo_root = Path(repo_root)
    out: list[str] = []
    seen: set[str] = set()

    for raw in roots:
        r = (raw or "").strip().replace("\\", "/").lstrip("/")
        if not r:
            continue
        full = (repo_root / r).resolve()
        try:
            full.relative_to(repo_root.resolve())
        except ValueError:
            continue
        if full.is_file():
            rel = str(full.relative_to(repo_root)).replace("\\", "/")
            if rel not in seen and not _path_should_skip(rel):
                seen.add(rel)
                out.append(rel)
                if len(out) >= max_files:
                    return out
        elif full.is_dir():
            for f in sorted(full.rglob("*")):
                if not f.is_file():
                    continue
                rel = str(f.relative_to(repo_root)).replace("\\", "/")
                if _path_should_skip(rel):
                    continue
                if rel not in seen:
                    seen.add(rel)
                    out.append(rel)
                    if len(out) >= max_files:
                        return out
    return out


def _walk_whole_repo(repo_root, *, max_files: int) -> list[str]:
    from pathlib import Path

    repo_root = Path(repo_root)
    out: list[str] = []
    for f in sorted(repo_root.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(repo_root)).replace("\\", "/")
        if _path_should_skip(rel):
            continue
        out.append(rel)
        if len(out) >= max_files:
            break
    return out


def _walk_repo_prioritized(repo_root, *, max_files: int) -> list[str]:
    """
    Deep codebase scan: enumerate likely application source trees first (src/, cmd/, …),
    then the remainder. Same skip rules as full walk.
    """
    from pathlib import Path

    repo_root = Path(repo_root)
    out: list[str] = []
    seen: set[str] = set()

    def try_add(rel: str) -> bool:
        if rel in seen or _path_should_skip(rel):
            return False
        seen.add(rel)
        out.append(rel)
        return True

    for dirname in sorted(_PRIORITY_ROOT_DIRS):
        if len(out) >= max_files:
            return out
        d = repo_root / dirname
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if len(out) >= max_files:
                return out
            if not f.is_file():
                continue
            rel = str(f.relative_to(repo_root)).replace("\\", "/")
            try_add(rel)

    for f in sorted(repo_root.rglob("*")):
        if len(out) >= max_files:
            break
        if not f.is_file():
            continue
        rel = str(f.relative_to(repo_root)).replace("\\", "/")
        try_add(rel)

    return out


async def pre_triage_node(state: AgentState) -> dict:
    """
    Classify changed files by observability relevance.
      - quick:      user-selected paths only (required via API); all expanded files analyzed
      - full:       whole repo (or optional path scope), LLM classification for ambiguous files
      - repository: prioritized deep walk (src/, cmd/, … first), then rest; LLM classification
    """
    await publish_progress(state, "triaging", 15, "Classifying changed files...", stage_index=2)

    request = state["request"]
    analysis_type = request.get("analysis_type", "full")
    cfg = _TYPE_CONFIG.get(analysis_type, _TYPE_CONFIG["full"])

    requested = list(request.get("changed_files") or [])
    repo_path = state.get("repo_path")
    raw_files: list[str] = []

    if repo_path:
        if requested:
            raw_files = _expand_repo_roots(repo_path, requested, max_files=cfg["file_cap"])
            if not raw_files:
                log.warning(
                    "scope_paths_expanded_empty",
                    requested=requested,
                    job_id=state.get("job_id"),
                )
        elif analysis_type == "quick":
            raw_files = []
            log.warning(
                "quick_analysis_missing_scope",
                job_id=state.get("job_id"),
            )
        elif analysis_type == "repository":
            raw_files = _walk_repo_prioritized(repo_path, max_files=cfg["file_cap"])
        else:
            raw_files = _walk_whole_repo(repo_path, max_files=cfg["file_cap"])

    # Cap total files
    raw_files = raw_files[:cfg["file_cap"]]

    classified: list[dict] = []
    for file_path in raw_files:
        score = _quick_classify(file_path)
        classified.append({
            "path": file_path,
            "language": _detect_language(file_path),
            "relevance_score": score,
            "content": None,
        })

    # Quick runs only on user-selected scope — treat every expanded file as in-scope for analysis
    if analysis_type == "quick" and requested:
        for f in classified:
            f["relevance_score"] = 2

    # Content-based heuristic pass: peek at first 2KB of ambiguous files
    # to promote/demote before expensive LLM call
    if state.get("repo_path"):
        from pathlib import Path as _P
        _repo = _P(state["repo_path"])
        for f in classified:
            if f["relevance_score"] != 1:
                continue
            try:
                _fp = _repo / f["path"]
                if _fp.exists():
                    _head = _fp.read_text(encoding="utf-8", errors="replace")[:2048]
                    f["relevance_score"] = _content_heuristic(_head, f["path"])
            except Exception:
                pass

    # LLM classification for remaining ambiguous files (only for full / repository)
    ambiguous = [f for f in classified if f["relevance_score"] == 1]
    llm_succeeded = False
    if cfg["llm_classify"] and ambiguous and len(ambiguous) <= 40:
        try:
            ambiguous_paths = {f["path"] for f in ambiguous}
            classified = await _llm_classify(classified, ambiguous, state)
            llm_succeeded = True
            # Log aggregate outcome (not per-file to avoid noise on large repos)
            after_map = {f["path"]: f["relevance_score"] for f in classified if f["path"] in ambiguous_paths}
            promoted = sum(1 for score in after_map.values() if score >= 2)
            demoted = sum(1 for score in after_map.values() if score == 0)
            log.info(
                "llm_classify_decision",
                ambiguous_files=len(ambiguous),
                promoted=promoted,
                demoted=demoted,
                job_id=state.get("job_id"),
            )
        except Exception as e:
            log.warning("haiku_triage_failed_using_heuristics", error=str(e))

    # If LLM unavailable or skipped, promote score-1 files so they still get analyzed
    if not llm_succeeded:
        for f in classified:
            if f["relevance_score"] == 1:
                f["relevance_score"] = 2

    # Load content for files that meet the minimum relevance threshold
    min_score = cfg["content_min_score"]
    if state.get("repo_path"):
        from pathlib import Path
        repo = Path(state["repo_path"])
        for f in classified:
            if f["relevance_score"] >= min_score:
                try:
                    content_path = repo / f["path"]
                    if content_path.exists():
                        f["content"] = content_path.read_text(encoding="utf-8", errors="replace")[:8000]
                except Exception:
                    pass

    relevant_count = sum(1 for f in classified if f["relevance_score"] >= min_score and f.get("content"))

    # Scan loaded files for lumis-ignore comments
    suppressed = _scan_lumis_ignore(classified)
    if suppressed:
        log.info("lumis_ignore_found", count=len(suppressed), job_id=state["job_id"])

    # Log individual triage decisions only for small batches (avoids log flood on repo scans)
    suppressed_paths = {s["file_path"] for s in suppressed}
    if len(classified) <= 60:
        for f in classified:
            action = "included" if f["relevance_score"] >= min_score else "excluded"
            reason: str | None = None
            if f["path"] in suppressed_paths:
                reason = "lumis_ignore"
            elif action == "excluded":
                reason = "score_threshold"
            log.debug(
                "file_triaged",
                file=f["path"],
                score=f["relevance_score"],
                action=action,
                **({"reason": reason} if reason else {}),
                job_id=state.get("job_id"),
            )

    log.info(
        "triage_complete",
        analysis_type=analysis_type,
        total=len(classified),
        relevant=relevant_count,
        job_id=state["job_id"],
    )

    for f in classified:
        if f["relevance_score"] >= min_score and f.get("content"):
            await publish_file_status(state, f["path"], "pending", f.get("language") or "")

    await publish_thought(
        state, "pre_triage",
        f"Classified {len(classified)} files — {relevant_count} relevant for analysis",
        status="done",
    )
    await publish_progress(
        state, "triaging", 20, f"Found {relevant_count} relevant files.",
        stage_index=2, files_total=relevant_count,
    )

    return {"changed_files": classified, "suppressed": suppressed}


def _scan_lumis_ignore(files: list[dict]) -> list[dict]:
    """
    Scan file contents for lumis-ignore annotations.
    Supports:
      - // lumis-ignore   (Go, JS, TS, Java)
      - # lumis-ignore    (Python, Terraform)
    Returns a list of {"file_path": str, "line": int} dicts.
    """
    suppressed: list[dict] = []
    for f in files:
        content = f.get("content")
        if not content:
            continue
        for line_no, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.endswith("// lumis-ignore") or stripped.endswith("# lumis-ignore"):
                suppressed.append({"file_path": f["path"], "line": line_no + 1})
    return suppressed


_LLM_TRIAGE_SYSTEM = """\
You are an expert observability engineer performing file triage for instrumentation analysis.
Your job: classify source files by their relevance to observability (traces, logs, metrics, spans).
Return ONLY a valid JSON array. No markdown fences, no explanation. Start directly with [.

## Scoring rules

Score 2 (HIGH — must analyze):
- HTTP handlers, endpoints, routes, controllers
- Database access: repository, DAO, store, DB client calls
- External API calls: HTTP clients, gRPC clients
- Message producers/consumers: Kafka, RabbitMQ, SQS, Pub/Sub
- Async workers, Celery tasks, job processors
- Critical business logic: payment, order, checkout, transaction, inventory, auth
- Server bootstrap / application factory / main entry point
- Auth middleware, error boundaries, global exception handlers
- WebSocket gateways, Socket.io handlers

Score 1 (LOW — analyze only if budget allows):
- Data models / schemas with no logic (just struct/interface definitions)
- Config files with DB connection strings or OTel settings
- Simple validators, formatters, converters
- ORM entities with lifecycle hooks
- Prisma schema files

Score 0 (DISCARD — never analyze):
- Tests, specs, fixtures, mocks, factories, snapshots
- Barrel files (only re-exports: export * from / export { } from)
- Pure type/interface files with no runtime logic
- Constants-only files
- Generated code (protobuf, mappers, stringer)
- Docs, assets, config tooling, CI/CD, lockfiles
- Migrations (Alembic, Django, TypeORM)

## Content indicators for ambiguous files (index.ts, utils.py, helpers.go):
- Contains app.listen(), createServer(), express(), FastAPI() → score 2
- Contains @app.route, @router.get, @celery.task → score 2
- Contains sql.Open(), gorm.Open(), kafka.NewConsumer() → score 2
- Contains ONLY re-exports or type definitions → score 0
"""

_LLM_TRIAGE_USER = """\
Classify each file below by observability relevance (0/1/2).

Files:
{file_list}

Reply with ONLY a JSON array: [{{"path": "...", "score": 0|1|2}}, ...]"""


async def _llm_classify(
    all_files: list[dict],
    ambiguous: list[dict],
    state: AgentState,
) -> list[dict]:
    """Use triage model to classify ambiguous files with enriched KB prompt."""
    from apps.agent.core.config import settings
    from apps.agent.llm.chat_completion import chat_complete

    provider = state.get("request", {}).get("llm_provider", "anthropic")
    if provider == "cerebra_ai":
        model = settings.cerebra_ai_model_triage
    else:
        model = settings.anthropic_model_triage

    file_list = "\n".join(f"- {f['path']}" for f in ambiguous)

    resp = await chat_complete(
        system=_LLM_TRIAGE_SYSTEM,
        user=_LLM_TRIAGE_USER.format(file_list=file_list),
        model=model,
        max_tokens=1024,
        provider=provider,
        base_url=settings.cerebra_ai_base_url,
        api_key=settings.anthropic_api_key if provider == "anthropic" else settings.cerebra_ai_api_key,
        temperature=settings.cerebra_ai_temperature if provider == "cerebra_ai" else 0.3,
        top_p=settings.cerebra_ai_top_p if provider == "cerebra_ai" else 0.9,
        timeout=settings.cerebra_ai_timeout if provider == "cerebra_ai" else 120,
        assistant_prefill="[" if provider == "anthropic" else None,
    )

    raw = resp.text.strip()
    if not raw.startswith("["):
        raw = "[" + raw
    match = re.search(r'\[.*?\]', raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array in response: {raw[:200]}")
    scores = json.loads(match.group())
    score_map = {s["path"]: s["score"] for s in scores}

    for f in all_files:
        if f["path"] in score_map:
            f["relevance_score"] = score_map[f["path"]]

    log.info(
        "llm_classify_completed",
        model=model,
        provider=provider,
        files_classified=len(score_map),
        job_id=state.get("job_id"),
    )
    return all_files
