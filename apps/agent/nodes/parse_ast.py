"""Node 3: Parse AST and build call graph."""
from __future__ import annotations

import re
import structlog

from apps.agent.nodes.base import publish_progress
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
    await publish_progress(state, "parsing", 25, "Parsing code structure...")

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
    await publish_progress(state, "parsing", 35, f"Found {len(call_graph.nodes)} code nodes.")

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
        }
    }


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
