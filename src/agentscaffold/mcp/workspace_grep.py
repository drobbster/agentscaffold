"""Scoped workspace ripgrep for MCP agents (Plan 246)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def workspace_grep(
    root: Path,
    pattern: str,
    *,
    path: str | None = None,
    glob: str | None = None,
    max_hits: int = 50,
) -> dict[str, Any]:
    """Run ripgrep under ``root`` with path sandboxing.

    Returns structured hits. Rejects paths that escape the project root.
    """
    if not pattern or not str(pattern).strip():
        return {"error": "pattern is required."}

    root = root.resolve()
    search_root = root
    if path:
        if Path(path).is_absolute():
            candidate = Path(path).resolve()
        else:
            candidate = (root / path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return {
                "error": f"path {path!r} escapes project root {root}",
                "sandbox_rejected": True,
            }
        if not candidate.exists():
            return {"error": f"path not found: {path}", "sandbox_rejected": False}
        search_root = candidate

    rg = shutil.which("rg")
    if rg is None:
        return _python_fallback_grep(root, search_root, pattern, glob=glob, max_hits=max_hits)

    limit = str(max(1, max_hits))
    cmd = [rg, "--json", "-m", limit, "--", pattern, str(search_root)]
    if glob:
        cmd = [rg, "--json", "-m", limit, "-g", glob, "--", pattern, str(search_root)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        return {"error": "ripgrep timed out", "hits": [], "count": 0}

    hits: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        if '"type":"match"' not in line and '"type": "match"' not in line:
            # still try parse
            pass
        try:
            import json

            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "match":
            continue
        data = obj.get("data") or {}
        path_text = (data.get("path") or {}).get("text") or ""
        line_num = data.get("line_number") or 0
        lines = data.get("lines") or {}
        text = (lines.get("text") or "").rstrip("\n")
        try:
            rel = str(Path(path_text).resolve().relative_to(root))
        except Exception:
            rel = path_text
        hits.append({"path": rel, "line": line_num, "text": text[:500]})
        if len(hits) >= max_hits:
            break

    return {
        "pattern": pattern,
        "path": path,
        "glob": glob,
        "hits": hits,
        "count": len(hits),
        "engine": "ripgrep",
        "truncated": len(hits) >= max_hits,
    }


def _python_fallback_grep(
    root: Path,
    search_root: Path,
    pattern: str,
    *,
    glob: str | None,
    max_hits: int,
) -> dict[str, Any]:
    """Minimal fallback when ``rg`` is not installed."""
    import fnmatch
    import re

    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return {"error": f"invalid pattern: {exc}"}

    hits: list[dict[str, Any]] = []
    for fp in search_root.rglob("*"):
        if not fp.is_file():
            continue
        if glob and not fnmatch.fnmatch(fp.name, glob):
            continue
        # Skip common noise
        parts = set(fp.parts)
        if parts & {".git", ".venv", "node_modules", ".scaffold", "__pycache__"}:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                try:
                    rel = str(fp.resolve().relative_to(root))
                except Exception:
                    rel = str(fp)
                hits.append({"path": rel, "line": i, "text": line[:500]})
                if len(hits) >= max_hits:
                    return {
                        "pattern": pattern,
                        "path": None,
                        "glob": glob,
                        "hits": hits,
                        "count": len(hits),
                        "engine": "python_fallback",
                        "truncated": True,
                    }
    return {
        "pattern": pattern,
        "path": None,
        "glob": glob,
        "hits": hits,
        "count": len(hits),
        "engine": "python_fallback",
        "truncated": False,
    }
