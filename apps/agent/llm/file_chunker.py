"""Semantic file chunking for files that exceed the LLM context budget.

Splits at function/method boundaries (regex-based, matching parse_ast.py patterns).
Each chunk includes the file header (imports/package) and adjacent function signatures.
"""
from __future__ import annotations

import re

import structlog

from apps.agent.llm.token_budget import estimate_tokens

log = structlog.get_logger(__name__)

# Regex patterns matching function definitions per language (same as parse_ast.py)
_FUNCTION_PATTERNS: dict[str, re.Pattern] = {
    "go": re.compile(r"^(func\s+(?:\([^)]+\)\s+)?\w+\s*\([^)]*\).*?\{)", re.MULTILINE),
    "python": re.compile(r"^((?:async\s+)?def\s+\w+\s*\([^)]*\)\s*(?:->.*?)?:)", re.MULTILINE),
    "java": re.compile(
        r"^(\s*(?:public|private|protected)?\s*(?:static\s+)?(?:async\s+)?\w+(?:<[^>]*>)?\s+\w+\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{)",
        re.MULTILINE,
    ),
    "typescript": re.compile(
        r"^((?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\)|(?:export\s+)?const\s+\w+\s*=\s*(?:async\s+)?\([^)]*\)\s*(?::\s*\w+)?\s*=>)",
        re.MULTILINE,
    ),
    "javascript": re.compile(
        r"^((?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\)|(?:export\s+)?const\s+\w+\s*=\s*(?:async\s+)?\([^)]*\)\s*=>)",
        re.MULTILINE,
    ),
}

# Languages where file "header" is imports + package statement
_HEADER_PATTERNS: dict[str, re.Pattern] = {
    "go": re.compile(r"^(?:package\s+\w+|import\s+[\s\S]*?\)|\s*$)", re.MULTILINE),
    "python": re.compile(r"^(?:from\s+|import\s+|#)", re.MULTILINE),
    "java": re.compile(r"^(?:package\s+|import\s+)", re.MULTILINE),
    "typescript": re.compile(r"^(?:import\s+|export\s+type\s)", re.MULTILINE),
    "javascript": re.compile(r"^(?:import\s+|const\s+\{.*\}\s*=\s*require)", re.MULTILINE),
}


def _extract_header(content: str, language: str | None) -> str:
    """Extract the file header (imports, package declaration) before any function."""
    if not language or language not in _FUNCTION_PATTERNS:
        lines = content.split("\n")
        header_lines = []
        for line in lines[:40]:
            stripped = line.strip()
            if not stripped or stripped.startswith(("import ", "from ", "package ", "#", "//")):
                header_lines.append(line)
            else:
                break
        return "\n".join(header_lines)

    pat = _FUNCTION_PATTERNS[language]
    m = pat.search(content)
    if m:
        return content[:m.start()].rstrip()
    return content[:min(len(content), 2000)]


def _split_into_functions(content: str, language: str | None) -> list[dict]:
    """
    Split file content into a list of function blocks.
    Returns [{"signature": str, "body": str, "line_start": int, "line_end": int}].
    """
    if not language or language not in _FUNCTION_PATTERNS:
        return [{"signature": "", "body": content, "line_start": 1, "line_end": content.count("\n") + 1}]

    pat = _FUNCTION_PATTERNS[language]
    matches = list(pat.finditer(content))
    if not matches:
        return [{"signature": "", "body": content, "line_start": 1, "line_end": content.count("\n") + 1}]

    functions = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].rstrip()
        line_start = content[:start].count("\n") + 1
        line_end = content[:end].count("\n") + 1
        functions.append({
            "signature": m.group(1).strip(),
            "body": body,
            "line_start": line_start,
            "line_end": line_end,
        })
    return functions


def chunk_file(
    file: dict,
    token_budget: int,
    overlap_signatures: int = 3,
) -> list[dict]:
    """
    Split a large file into chunks at function boundaries.

    Each chunk is a dict compatible with the batch analysis pipeline:
      - path: original file path
      - language: original language
      - content: header + function bodies for this chunk
      - relevance_score: inherited from original
      - _chunk_index: 0-based chunk index
      - _chunk_total: total chunks for this file
      - _is_chunk: True

    Never truncates a function body. If a single function exceeds the budget,
    it gets its own chunk (potentially over-budget, but never discarded).
    """
    content = file.get("content") or ""
    language = file.get("language")
    header = _extract_header(content, language)
    header_tokens = estimate_tokens(header)

    functions = _split_into_functions(content, language)
    if not functions:
        return [_make_chunk(file, content, 0, 1)]

    available = max(token_budget - header_tokens - 500, 2000)

    chunks: list[dict] = []
    current_fns: list[dict] = []
    current_tokens = 0

    for i, fn in enumerate(functions):
        fn_tokens = estimate_tokens(fn["body"])

        if fn_tokens > available:
            if current_fns:
                chunks.append(_build_chunk_content(
                    file, header, current_fns, functions, len(chunks),
                    overlap_signatures,
                ))
                current_fns = []
                current_tokens = 0
            chunks.append(_build_chunk_content(
                file, header, [fn], functions, len(chunks),
                overlap_signatures,
            ))
            continue

        if current_tokens + fn_tokens > available and current_fns:
            chunks.append(_build_chunk_content(
                file, header, current_fns, functions, len(chunks),
                overlap_signatures,
            ))
            current_fns = [fn]
            current_tokens = fn_tokens
        else:
            current_fns.append(fn)
            current_tokens += fn_tokens

    if current_fns:
        chunks.append(_build_chunk_content(
            file, header, current_fns, functions, len(chunks),
            overlap_signatures,
        ))

    total = len(chunks)
    for i, c in enumerate(chunks):
        c["_chunk_index"] = i
        c["_chunk_total"] = total

    log.info(
        "file_chunked",
        path=file.get("path"),
        total_functions=len(functions),
        chunks=total,
        token_budget=token_budget,
    )
    return chunks


def _build_chunk_content(
    file: dict,
    header: str,
    fns: list[dict],
    all_fns: list[dict],
    chunk_idx: int,
    overlap_sigs: int,
) -> dict:
    """Build a chunk dict with header + function bodies + adjacent signatures."""
    parts = [header, ""]

    fn_start = fns[0]["line_start"] if fns else 1
    fn_end = fns[-1]["line_end"] if fns else 1

    all_fn_idx_start = next((i for i, f in enumerate(all_fns) if f is fns[0]), 0)
    all_fn_idx_end = all_fn_idx_start + len(fns)

    before_sigs = [
        f"// [context] {f['signature']}"
        for f in all_fns[max(0, all_fn_idx_start - overlap_sigs):all_fn_idx_start]
        if f["signature"]
    ]
    after_sigs = [
        f"// [context] {f['signature']}"
        for f in all_fns[all_fn_idx_end:all_fn_idx_end + overlap_sigs]
        if f["signature"]
    ]

    if before_sigs:
        parts.append("// --- adjacent functions above (signatures only) ---")
        parts.extend(before_sigs)
        parts.append("")

    for fn in fns:
        parts.append(fn["body"])
        parts.append("")

    if after_sigs:
        parts.append("// --- adjacent functions below (signatures only) ---")
        parts.extend(after_sigs)

    content = "\n".join(parts)
    return _make_chunk(file, content, chunk_idx, 0)


def _make_chunk(file: dict, content: str, chunk_idx: int, chunk_total: int) -> dict:
    return {
        "path": file.get("path", ""),
        "language": file.get("language"),
        "relevance_score": file.get("relevance_score", 2),
        "content": content,
        "_is_chunk": True,
        "_chunk_index": chunk_idx,
        "_chunk_total": chunk_total,
    }
