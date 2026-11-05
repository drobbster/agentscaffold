"""Scoped workspace ripgrep for MCP agents."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def extra_path_targets(root: Path) -> dict[Path, str]:
    """Files ``graph.extra_paths`` adds to the project at *root*: real path -> File path."""
    from agentscaffold.config import GraphConfig
    from agentscaffold.graph.source_roots import configured_extra_paths, scan_extra_paths
    from agentscaffold.paths import resolve_node_path

    globs = configured_extra_paths(root)
    if not globs:
        return {}
    targets: dict[Path, str] = {}
    for node_path in scan_extra_paths(root, GraphConfig(extra_paths=globs)).files:
        full = resolve_node_path(root, node_path)
        if full is not None:
            targets[full.resolve()] = node_path
    return targets


def workspace_grep(
    root: Path,
    pattern: str,
    *,
    path: str | None = None,
    glob: str | None = None,
    max_hits: int = 50,
) -> dict[str, Any]:
    """Run ripgrep under ``root`` with path sandboxing.

    Returns structured hits. Rejects paths that escape the project root, except
    the project's ``graph.extra_paths`` files, named ``@repo/...``.
    """
    from agentscaffold.repo_paths import is_repo_path

    if not pattern or not str(pattern).strip():
        return {"error": "pattern is required."}

    root = root.resolve()
    extras = extra_path_targets(root)
    targets: list[Path] = [root, *extras]
    if path and is_repo_path(path):
        wanted = path.rstrip("/")
        targets = [p for p, n in extras.items() if n == wanted or n.startswith(wanted + "/")]
        if not targets:
            return {
                "error": f"path {path!r} is not an extra-path file of project root {root}",
                "sandbox_rejected": True,
            }
    elif path:
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
        targets = [candidate]

    rg = shutil.which("rg")
    if rg is None:
        return _python_fallback_grep(
            root, targets, pattern, glob=glob, max_hits=max_hits, extras=extras
        )

    limit = str(max(1, max_hits))
    cmd = [rg, "--json", "-m", limit, "--", pattern, *map(str, targets)]
    if glob:
        cmd = [rg, "--json", "-m", limit, "-g", glob, "--", pattern, *map(str, targets)]

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
        hits.append(
            {"path": _hit_path(path_text, root, extras), "line": line_num, "text": text[:500]}
        )
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


def _hit_path(path_text: str, root: Path, extras: dict[Path, str]) -> str:
    resolved = Path(path_text).resolve()
    if resolved in extras:
        return extras[resolved]
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return path_text


def _python_fallback_grep(
    root: Path,
    targets: list[Path],
    pattern: str,
    *,
    glob: str | None,
    max_hits: int,
    extras: dict[Path, str],
) -> dict[str, Any]:
    """Minimal fallback when ``rg`` is not installed."""
    import fnmatch
    import re

    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return {"error": f"invalid pattern: {exc}"}

    hits: list[dict[str, Any]] = []
    files = (fp for t in targets for fp in ([t] if t.is_file() else t.rglob("*")))
    for fp in files:
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
                hits.append(
                    {"path": _hit_path(str(fp), root, extras), "line": i, "text": line[:500]}
                )
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
