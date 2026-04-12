"""Node 3: Parse AST and build call graph."""
from __future__ import annotations

import re
import structlog

from apps.agent.nodes.base import publish_progress, publish_thought
from apps.agent.schemas import AgentState, CallGraph, CallNode

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Observability import detection
# ---------------------------------------------------------------------------

_OBS_IMPORT_PATTERNS: dict[str, dict[str, list[str]]] = {
    "otel": [
        r"opentelemetry",
        r"go\.opentelemetry\.io",
        r"@opentelemetry/",
        r"io\.opentelemetry",
    ],
    "datadog": [
        r"ddtrace",
        r"dd-trace",
        r'"github\.com/DataDog',
        r"from datadog",
        r"import datadog",
        r"require\(['\"]dd-trace",
    ],
}


def _detect_obs_imports(content: str, language: str) -> str:
    """
    Scan file content for known observability library imports.

    Returns one of:
      "otel"    — OpenTelemetry SDK detected
      "datadog" — Datadog dd-trace / ddsketch detected
      "mixed"   — Both OTel and Datadog imports present
      "none"    — No recognised obs. library found
    """
    found: set[str] = set()
    for lib, patterns in _OBS_IMPORT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                found.add(lib)
                break

    if "otel" in found and "datadog" in found:
        return "mixed"
    if "otel" in found:
        return "otel"
    if "datadog" in found:
        return "datadog"
    return "none"


async def parse_ast_node(state: AgentState) -> dict:
    """
    Parse relevant files with tree-sitter and build a call graph.
    Identifies: entry points, I/O nodes, error paths, and observability imports.
    """
    await publish_progress(state, "parsing", 25, "Parsing code structure...", stage_index=3)

    relevant_files = [f for f in state["changed_files"] if f["relevance_score"] >= 1]
    call_graph = CallGraph()

    # Per-file obs import detection: path → "otel" | "datadog" | "mixed" | "none"
    file_obs_imports: dict[str, str] = {}

    for file_info in relevant_files:
        if not file_info.get("content"):
            continue

        language = file_info.get("language")
        if language not in ("go", "python", "java", "typescript", "javascript"):
            continue

        content = file_info["content"]
        file_obs_imports[file_info["path"]] = _detect_obs_imports(content, language)

        try:
            nodes = _extract_nodes(file_info["path"], content, language)
            for node in nodes:
                call_graph.nodes[f"{file_info['path']}:{node.name}"] = node
                if node.node_type == "handler":
                    call_graph.entry_points.append(f"{file_info['path']}:{node.name}")
                elif node.node_type in ("db_call", "http_client", "cache", "queue"):
                    call_graph.io_nodes.append(f"{file_info['path']}:{node.name}")
        except Exception as e:
            log.warning("ast_parse_failed", file=file_info["path"], error=str(e))

    # Second pass: populate directed call graph edges (callers / callees)
    # For each node, scan its function body for calls to other known functions
    _populate_call_edges(call_graph, relevant_files)

    log.info(
        "ast_parsed",
        nodes=len(call_graph.nodes),
        entry_points=len(call_graph.entry_points),
        io_nodes=len(call_graph.io_nodes),
        files_with_obs=sum(1 for v in file_obs_imports.values() if v != "none"),
    )
    await publish_thought(
        state, "parse_ast",
        f"Built call graph: {len(call_graph.nodes)} nodes, {len(call_graph.entry_points)} entry points, {len(call_graph.io_nodes)} I/O nodes",
        status="done",
    )
    await publish_progress(state, "parsing", 35, f"Found {len(call_graph.nodes)} code nodes.", stage_index=3)

    # For full/repository runs, do a lightweight pass over the entire repo
    # to build a complete function name index for better call graph edges
    analysis_type = state.get("request", {}).get("analysis_type", "quick")
    full_repo_index: dict[str, list[str]] = {}
    if analysis_type in ("full", "repository") and state.get("repo_path"):
        full_repo_index = _index_full_repo_topology(state["repo_path"])
        log.info("full_repo_index_built", functions=sum(len(v) for v in full_repo_index.values()))

    summary = generate_call_graph_summary(call_graph)

    return {
        "call_graph": {
            "nodes": {
                k: {
                    "name": v.name,
                    "file_path": v.file_path,
                    "line": v.line,
                    "node_type": v.node_type,
                    "callers": v.callers,
                    "callees": v.callees,
                }
                for k, v in call_graph.nodes.items()
            },
            "entry_points": call_graph.entry_points,
            "io_nodes": call_graph.io_nodes,
            "error_paths": call_graph.error_paths,
            "file_obs_imports": file_obs_imports,
            "summary": summary,
            "full_repo_index": full_repo_index,
        }
    }


_EXT_TO_LANG: dict[str, str] = {
    ".go": "go", ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".java": "java",
}

_FUNC_PATTERNS: dict[str, re.Pattern] = {
    "go": re.compile(r"func\s+(?:\([^)]+\)\s+)?(\w+)\s*\("),
    "python": re.compile(r"(?:async\s+)?def\s+(\w+)\s*\("),
    "typescript": re.compile(r"(?:async\s+)?function\s+(\w+)\s*\(|(?:export\s+)?(?:async\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\("),
    "javascript": re.compile(r"(?:async\s+)?function\s+(\w+)\s*\(|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\("),
    "java": re.compile(r"(?:public|private|protected|static)\s+\w+\s+(\w+)\s*\("),
}


def _index_full_repo_topology(repo_path: str) -> dict[str, list[str]]:
    """
    Lightweight pass over all repo source files to map function names to file paths.
    Does NOT create full CallNode objects — only an index for cross-referencing.
    """
    from pathlib import Path

    repo = Path(repo_path)
    skip = {".git", "__pycache__", "node_modules", "vendor", "dist", "build", ".venv", "venv", ".terraform"}
    index: dict[str, list[str]] = {}
    files_scanned = 0

    for p in repo.rglob("*"):
        if not p.is_file() or any(s in p.parts for s in skip):
            continue
        lang = _EXT_TO_LANG.get(p.suffix.lower())
        if not lang:
            continue
        pattern = _FUNC_PATTERNS.get(lang)
        if not pattern:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")[:8000]
            rel_path = str(p.relative_to(repo))
            for m in pattern.finditer(content):
                name = m.group(1) or (m.group(2) if m.lastindex and m.lastindex >= 2 else None)
                if name:
                    index.setdefault(name, []).append(rel_path)
            files_scanned += 1
            if files_scanned >= 2000:
                break
        except Exception:
            pass

    return index


def _populate_call_edges(call_graph: CallGraph, files: list[dict]) -> None:
    """
    Second pass: for each node, scan its function body to find calls to other
    known functions, then populate node.callees and the reciprocal node.callers.

    Strategy:
    - Build a lookup of all known function names → node key
    - For each node, extract a body window (next 60 lines after the function definition)
    - Match function-call patterns against known names
    - Set callee/caller relationships
    """
    # Build name → [node_key] index (names may not be unique across files)
    name_index: dict[str, list[str]] = {}
    for key, node in call_graph.nodes.items():
        name_index.setdefault(node.name, []).append(key)

    # Build file content lookup
    file_content: dict[str, str] = {}
    for f in files:
        if f.get("content"):
            file_content[f["path"]] = f["content"]

    for key, node in call_graph.nodes.items():
        content = file_content.get(node.file_path, "")
        if not content:
            continue

        lines = content.split("\n")
        # Window: lines from the function definition onward (up to 60 lines)
        start = max(0, node.line - 1)
        body = "\n".join(lines[start: start + 60])

        for callee_name, callee_keys in name_index.items():
            if callee_name == node.name:
                continue
            # Match a function call: callee_name( or .callee_name(
            if re.search(r'\b' + re.escape(callee_name) + r'\s*\(', body):
                for callee_key in callee_keys:
                    # Add edge caller → callee
                    if callee_key not in node.callees:
                        node.callees.append(callee_key)
                    callee_node = call_graph.nodes.get(callee_key)
                    if callee_node and key not in callee_node.callers:
                        callee_node.callers.append(key)


def _extract_nodes(file_path: str, content: str, language: str) -> list[CallNode]:
    """Extract function/method nodes with type classification."""
    nodes = []

    if language == "go":
        # HTTP handlers: func (h *Handler) ServeHTTP or func handleX
        for m in re.finditer(r"func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", content):
            name = m.group(1)
            line = content[:m.start()].count("\n") + 1
            node_type = _classify_go_function(name, content[m.start():m.start()+500])
            nodes.append(CallNode(name=name, file_path=file_path, line=line, node_type=node_type))

    elif language == "python":
        for m in re.finditer(r"(?:async\s+)?def\s+(\w+)\s*\(", content):
            name = m.group(1)
            line = content[:m.start()].count("\n") + 1
            node_type = _classify_python_function(name, content[m.start():m.start()+500])
            nodes.append(CallNode(name=name, file_path=file_path, line=line, node_type=node_type))

    elif language in ("typescript", "javascript"):
        for m in re.finditer(r"(?:async\s+)?function\s+(\w+)\s*\(|const\s+(\w+)\s*=\s*(?:async\s+)?\(", content):
            name = m.group(1) or m.group(2)
            if not name:
                continue
            line = content[:m.start()].count("\n") + 1
            node_type = _classify_js_function(name, content[m.start():m.start()+500])
            nodes.append(CallNode(name=name, file_path=file_path, line=line, node_type=node_type))

    return nodes


def _classify_go_function(name: str, context: str) -> str:
    lower = name.lower()
    ctx_lower = context.lower()
    if any(k in lower for k in ("handler", "handle", "serve", "controller")):
        return "handler"
    if any(k in ctx_lower for k in ("db.", "sql.", "query", "exec(")):
        return "db_call"
    if any(k in ctx_lower for k in ("http.get", "http.post", "client.do", "httpclient")):
        return "http_client"
    if any(k in ctx_lower for k in ("redis.", "cache.", "get(", "set(")):
        return "cache"
    if any(k in ctx_lower for k in ("kafka.", "publish(", "produce(", "rabbitmq")):
        return "queue"
    return "utility"


def _classify_python_function(name: str, context: str) -> str:
    lower = name.lower()
    ctx_lower = context.lower()
    if any(k in lower for k in ("handler", "handle", "view", "endpoint", "route")):
        return "handler"
    if any(k in ctx_lower for k in ("session.", "db.", "query(", "execute(")):
        return "db_call"
    if any(k in ctx_lower for k in ("requests.", "httpx.", "aiohttp.", "client.get")):
        return "http_client"
    if any(k in ctx_lower for k in ("redis.", "cache.", "get(", "set(")):
        return "cache"
    if any(k in ctx_lower for k in ("kafka", "publish", "produce", "celery", "delay(")):
        return "queue"
    return "utility"


def _classify_js_function(name: str, context: str) -> str:
    lower = name.lower()
    ctx_lower = context.lower()
    if any(k in lower for k in ("handler", "handle", "controller", "route", "middleware")):
        return "handler"
    if any(k in ctx_lower for k in ("prisma.", "sequelize.", "query(", "execute(")):
        return "db_call"
    if any(k in ctx_lower for k in ("fetch(", "axios.", "got.", "request(")):
        return "http_client"
    if any(k in ctx_lower for k in ("redis.", "cache.", "memcached.")):
        return "cache"
    if any(k in ctx_lower for k in ("kafka", "publish(", "produce(", "sqs.")):
        return "queue"
    return "utility"


# ---------------------------------------------------------------------------
# Call graph summary generation (injected into all batch prompts)
# ---------------------------------------------------------------------------

_NODE_TYPE_LABEL = {
    "handler": "HTTP/gRPC handler",
    "db_call": "database call",
    "http_client": "external HTTP call",
    "cache": "cache operation",
    "queue": "message queue",
    "utility": "utility",
}


def generate_call_graph_summary(call_graph: CallGraph, max_tokens: int = 6000) -> str:
    """
    Produce a compact text summary of the call graph for injection into
    LLM batch prompts. Covers entry points, I/O nodes, critical call chains,
    and external dependencies. Stays within `max_tokens` estimated budget.
    """
    lines: list[str] = ["## Service Call Graph (shared context)"]
    budget_chars = max_tokens * 4

    # Entry points
    if call_graph.entry_points:
        lines.append("\n### Entry points")
        for ep_key in call_graph.entry_points[:30]:
            node = call_graph.nodes.get(ep_key)
            if not node:
                continue
            callees_str = ""
            if node.callees:
                callee_names = []
                for ck in node.callees[:5]:
                    cn = call_graph.nodes.get(ck)
                    if cn:
                        label = _NODE_TYPE_LABEL.get(cn.node_type, cn.node_type)
                        callee_names.append(f"{cn.name} [{label}]")
                callees_str = " → " + " → ".join(callee_names)
            lines.append(f"  {node.file_path}: {node.name}(){callees_str}")

    # I/O nodes (DB, HTTP client, queue, cache)
    if call_graph.io_nodes:
        lines.append("\n### I/O nodes (need spans for observability)")
        for io_key in call_graph.io_nodes[:40]:
            node = call_graph.nodes.get(io_key)
            if not node:
                continue
            label = _NODE_TYPE_LABEL.get(node.node_type, node.node_type)
            callers_str = ""
            if node.callers:
                caller_names = [
                    call_graph.nodes[ck].name
                    for ck in node.callers[:3]
                    if ck in call_graph.nodes
                ]
                if caller_names:
                    callers_str = f" (called by: {', '.join(caller_names)})"
            lines.append(f"  {node.file_path}: {node.name}() [{label}]{callers_str}")

    # Critical chains: entry point → I/O node paths
    io_set = set(call_graph.io_nodes)
    chains: list[str] = []
    for ep_key in call_graph.entry_points[:15]:
        ep_node = call_graph.nodes.get(ep_key)
        if not ep_node:
            continue
        for callee_key in ep_node.callees:
            if callee_key in io_set:
                callee = call_graph.nodes.get(callee_key)
                if callee:
                    chains.append(
                        f"  {ep_node.name}() → {callee.name}() "
                        f"[{_NODE_TYPE_LABEL.get(callee.node_type, '')}]"
                    )
    if chains:
        lines.append("\n### Critical paths (entry point → I/O)")
        lines.extend(chains[:20])

    # Files with functions
    files_with_nodes: dict[str, int] = {}
    for node in call_graph.nodes.values():
        files_with_nodes[node.file_path] = files_with_nodes.get(node.file_path, 0) + 1
    if files_with_nodes:
        lines.append(f"\n### Files indexed: {len(files_with_nodes)} files, "
                      f"{len(call_graph.nodes)} functions total")

    summary = "\n".join(lines)
    if len(summary) > budget_chars:
        summary = summary[:budget_chars] + "\n... (truncated)"

    return summary
