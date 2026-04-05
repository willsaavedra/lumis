"""
Tree-sitter AST parser for Go, Python, Java, TypeScript/JavaScript.
Provides a unified interface for extracting structural information from source code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedNode:
    name: str
    node_type: str           # "function", "method", "class", "handler", "import"
    file_path: str
    line_start: int
    line_end: int
    language: str
    annotations: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)  # function names called by this node
    is_async: bool = False
    is_exported: bool = False


class ASTParser:
    """
    Unified AST parser that wraps tree-sitter grammars.
    Falls back to regex-based parsing when tree-sitter grammars are not available.
    """

    SUPPORTED_LANGUAGES = {"go", "python", "java", "typescript", "javascript"}

    def parse_file(self, file_path: str, content: str, language: str) -> list[ParsedNode]:
        """Parse a source file and return all structural nodes."""
        if language not in self.SUPPORTED_LANGUAGES:
            return []

        try:
            return self._parse_with_treesitter(file_path, content, language)
        except Exception:
            return self._parse_with_regex(file_path, content, language)

    def _parse_with_treesitter(self, file_path: str, content: str, language: str) -> list[ParsedNode]:
        """Attempt tree-sitter parsing."""
        # tree-sitter grammars must be compiled separately; fall back to regex
        raise NotImplementedError("tree-sitter grammar not compiled")

    def _parse_with_regex(self, file_path: str, content: str, language: str) -> list[ParsedNode]:
        """Regex-based fallback parser."""
        if language == "go":
            return self._parse_go(file_path, content)
        elif language == "python":
            return self._parse_python(file_path, content)
        elif language == "java":
            return self._parse_java(file_path, content)
        elif language in ("typescript", "javascript"):
            return self._parse_js(file_path, content, language)
        return []

    def _parse_go(self, file_path: str, content: str) -> list[ParsedNode]:
        nodes = []
        lines = content.split("\n")

        func_pattern = re.compile(r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(([^)]*)\)")
        for i, line in enumerate(lines, 1):
            m = func_pattern.match(line.strip())
            if m:
                name = m.group(1)
                is_exported = name[0].isupper() if name else False
                node_type = self._classify_go_node(name, "\n".join(lines[i-1:i+20]))
                nodes.append(ParsedNode(
                    name=name,
                    node_type=node_type,
                    file_path=file_path,
                    line_start=i,
                    line_end=i + 10,
                    language="go",
                    is_exported=is_exported,
                ))
        return nodes

    def _parse_python(self, file_path: str, content: str) -> list[ParsedNode]:
        nodes = []
        lines = content.split("\n")
        func_pattern = re.compile(r"^(async\s+)?def\s+(\w+)\s*\(")
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            m = func_pattern.match(stripped)
            if m:
                is_async = m.group(1) is not None
                name = m.group(2)
                node_type = self._classify_python_node(name, "\n".join(lines[i-1:i+20]))
                nodes.append(ParsedNode(
                    name=name,
                    node_type=node_type,
                    file_path=file_path,
                    line_start=i,
                    line_end=i + 10,
                    language="python",
                    is_async=is_async,
                    is_exported=not name.startswith("_"),
                ))
        return nodes

    def _parse_java(self, file_path: str, content: str) -> list[ParsedNode]:
        nodes = []
        lines = content.split("\n")
        method_pattern = re.compile(
            r"(?:public|private|protected)?\s+(?:static\s+)?(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+\s*)?\{"
        )
        for i, line in enumerate(lines, 1):
            m = method_pattern.search(line)
            if m:
                name = m.group(1)
                node_type = self._classify_java_node(name, line)
                nodes.append(ParsedNode(
                    name=name,
                    node_type=node_type,
                    file_path=file_path,
                    line_start=i,
                    line_end=i + 10,
                    language="java",
                ))
        return nodes

    def _parse_js(self, file_path: str, content: str, language: str) -> list[ParsedNode]:
        nodes = []
        lines = content.split("\n")
        patterns = [
            re.compile(r"(?:async\s+)?function\s+(\w+)\s*\("),
            re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\("),
            re.compile(r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)"),
        ]
        for i, line in enumerate(lines, 1):
            for pattern in patterns:
                m = pattern.search(line)
                if m:
                    name = m.group(1)
                    is_async = "async" in line[:m.start() + 30]
                    node_type = self._classify_js_node(name, line)
                    nodes.append(ParsedNode(
                        name=name,
                        node_type=node_type,
                        file_path=file_path,
                        line_start=i,
                        line_end=i + 10,
                        language=language,
                        is_async=is_async,
                    ))
                    break
        return nodes

    def _classify_go_node(self, name: str, context: str) -> str:
        lower = name.lower()
        ctx = context.lower()
        if any(k in lower for k in ("handler", "handle", "serve", "controller")):
            return "handler"
        if any(k in ctx for k in ("db.", "sql.", "query", "exec(")):
            return "db_call"
        if "http.get" in ctx or "http.post" in ctx or "client.do" in ctx:
            return "http_client"
        if any(k in ctx for k in ("redis.", "cache.")):
            return "cache"
        if any(k in ctx for k in ("kafka.", "publish(", "produce(")):
            return "queue"
        return "utility"

    def _classify_python_node(self, name: str, context: str) -> str:
        lower = name.lower()
        ctx = context.lower()
        if any(k in lower for k in ("handler", "view", "endpoint", "route")):
            return "handler"
        if any(k in ctx for k in ("session.", "db.", "query(")):
            return "db_call"
        if any(k in ctx for k in ("requests.", "httpx.", "aiohttp.")):
            return "http_client"
        if any(k in ctx for k in ("redis.", "cache.")):
            return "cache"
        if any(k in ctx for k in ("kafka", "celery", ".delay(")):
            return "queue"
        return "utility"

    def _classify_java_node(self, name: str, context: str) -> str:
        if "@RequestMapping" in context or "@GetMapping" in context or "@PostMapping" in context:
            return "handler"
        lower = name.lower()
        if any(k in lower for k in ("get", "find", "save", "delete", "update", "repository")):
            return "db_call"
        return "utility"

    def _classify_js_node(self, name: str, context: str) -> str:
        lower = name.lower()
        if any(k in lower for k in ("handler", "controller", "route", "middleware")):
            return "handler"
        if any(k in context.lower() for k in ("prisma.", "mongoose.", "sequelize.")):
            return "db_call"
        return "utility"


def detect_language(file_path: str) -> str | None:
    """Detect programming language from file extension."""
    ext_map = {
        ".go": "go",
        ".py": "python",
        ".java": "java",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".tf": "terraform",
        ".hcl": "terraform",
    }
    for ext, lang in ext_map.items():
        if file_path.endswith(ext):
            return lang
    return None
