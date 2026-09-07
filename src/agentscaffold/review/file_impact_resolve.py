"""Resolve a plan's File Impact paths to local, sibling, or skipped.

Review tools used to read ``PLAN_IMPACTS`` edges. Ingest only creates those
edges when the path is already a ``File`` in this project, so sibling
``src/...`` cells vanish and reviews vacuous-pass on the governance docs
that remain (L249-17 / Plan 271).

Resolution is markdown-first (``_extract_file_impact``), then local disk,
then the named ``implementation_project`` only. It does not walk every
registered root.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from agentscaffold.active_root import default_start
from agentscaffold.config import ConfigError, ScaffoldConfig, find_config, load_config
from agentscaffold.review.queries import get_plan_by_number, get_plan_impacted_files

Resolution = Literal["local", "sibling", "skipped"]

REASON_OUTSIDE = "paths_outside_project"
REASON_UNSET = "implementation_project_unset"
REASON_ABSOLUTE = "absolute_path_rejected"


class ImplementationProjectError(ConfigError):
    """``implementation_project`` is set but is not a registered project name."""


@dataclass
class ResolvedImpacts:
    """Resolved File Impact rows plus any sibling graphs to close."""

    rows: list[dict[str, Any]]
    _sibling_stores: list[Any] = field(default_factory=list)

    def close(self) -> None:
        for store in self._sibling_stores:
            try:
                store.close()
            except Exception:
                pass
        self._sibling_stores.clear()


def query_store(row: dict[str, Any], default: Any) -> Any:
    """Graph to query for this row (sibling store when resolved there)."""
    return row.get("_store") or default


def query_root(row: dict[str, Any], default: Path) -> Path:
    root = row.get("_root")
    return Path(root) if root is not None else default


@contextmanager
def resolved_impacts(
    store: Any,
    plan_number: int,
    *,
    root: Path | None = None,
    config: ScaffoldConfig | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Resolve File Impact rows and close any sibling graph on exit."""
    result = resolve_plan_impacted_files(store, plan_number, root=root, config=config)
    try:
        yield result.rows
    finally:
        result.close()


def resolve_plan_impacted_files(
    store: Any,
    plan_number: int,
    *,
    root: Path | None = None,
    config: ScaffoldConfig | None = None,
) -> ResolvedImpacts:
    """Return File Impact rows stamped with ``resolution`` and ``project``."""
    base = _resolve_base(store, plan_number, root)
    cfg = config if config is not None else load_config(find_config(start=base))
    current_name = _current_project_name(base, cfg)

    impl_name = getattr(cfg, "implementation_project", None) or None
    sibling = None
    sibling_store = None
    extra_stores: list[Any] = []
    if impl_name:
        sibling = _require_registered_project(impl_name)
        sibling_store = _open_project_graph(sibling.project_root)
        if sibling_store is not None:
            extra_stores.append(sibling_store)

    planned = _planned_paths(store, plan_number, base)
    if not planned:
        return ResolvedImpacts(rows=[], _sibling_stores=extra_stores)

    rows: list[dict[str, Any]] = []
    for item in planned:
        rel = item["path"]
        change = item.get("change_type", "")
        row = _resolve_one(
            rel,
            change,
            current_root=base,
            current_name=current_name,
            current_store=store,
            sibling=sibling,
            sibling_store=sibling_store,
            impl_name=impl_name,
        )
        rows.append(row)
    return ResolvedImpacts(rows=rows, _sibling_stores=extra_stores)


def _resolve_base(store: Any, plan_number: int, root: Path | None) -> Path:
    if root is not None:
        return Path(root)
    plan = get_plan_by_number(store, plan_number)
    plan_path = (plan or {}).get("p.filePath") or ""
    if plan_path:
        full = Path(str(plan_path))
        if not full.is_absolute():
            full = default_start() / str(plan_path)
        if full.is_file():
            from_layout = _project_root_from_plan_file(full)
            if from_layout is not None:
                return from_layout
            found = find_config(start=full.parent)
            if found is not None:
                return found.parent
    return default_start()


def _project_root_from_plan_file(plan_path: Path) -> Path | None:
    """``{root}/docs/ai/plans/*.md`` -> ``root``.

    ``find_config`` walks into a parent checkout that happens to have
    ``scaffold.yaml`` (this package, when tests index ``sample_repo``).
    Plan files live at the documented layout; use that ancestor first.
    """
    resolved = plan_path.resolve()
    parts = resolved.parts
    needle = ("docs", "ai", "plans")
    for i in range(len(parts) - 3):
        if parts[i : i + 3] == needle:
            return Path(*parts[:i])
    return None


def _planned_paths(store: Any, plan_number: int, root: Path) -> list[dict[str, str]]:
    from agentscaffold.graph.governance import _extract_file_impact

    plan = get_plan_by_number(store, plan_number)
    if plan is None:
        return []
    plan_path = plan.get("p.filePath") or ""
    full = Path(plan_path) if Path(str(plan_path)).is_absolute() else root / str(plan_path)
    if full.is_file():
        impacts = _extract_file_impact(full.read_text(encoding="utf-8", errors="replace"))
        if impacts:
            return impacts
    return [
        {"path": f.get("f.path", ""), "change_type": f.get("r.changeType", "")}
        for f in get_plan_impacted_files(store, plan_number)
        if f.get("f.path")
    ]


def _resolve_one(
    rel: str,
    change: str,
    *,
    current_root: Path,
    current_name: str,
    current_store: Any,
    sibling: Any,
    sibling_store: Any,
    impl_name: str | None,
) -> dict[str, Any]:
    language = _language_for(rel)
    if _is_absolute_or_home(rel):
        return _row(
            rel,
            change,
            language,
            resolution="skipped",
            project=None,
            reason=REASON_ABSOLUTE,
            store=current_store,
            root=current_root,
        )
    if (current_root / rel).is_file():
        return _row(
            rel,
            change,
            language,
            resolution="local",
            project=current_name,
            reason=None,
            store=current_store,
            root=current_root,
        )
    if sibling is not None:
        sib_root = Path(sibling.project_root)
        if (sib_root / rel).is_file():
            return _row(
                rel,
                change,
                language,
                resolution="sibling",
                project=sibling.name,
                reason=None,
                store=sibling_store or current_store,
                root=sib_root,
            )
        return _row(
            rel,
            change,
            language,
            resolution="skipped",
            project=sibling.name,
            reason=REASON_OUTSIDE,
            store=current_store,
            root=current_root,
        )
    return _row(
        rel,
        change,
        language,
        resolution="skipped",
        project=None,
        reason=REASON_UNSET if not impl_name else REASON_OUTSIDE,
        store=current_store,
        root=current_root,
    )


def _row(
    path: str,
    change: str,
    language: str,
    *,
    resolution: Resolution,
    project: str | None,
    reason: str | None,
    store: Any,
    root: Path,
) -> dict[str, Any]:
    return {
        "f.path": path,
        "f.language": language,
        "r.changeType": change,
        "resolution": resolution,
        "project": project,
        "reason": reason,
        "_store": store,
        "_root": root,
    }


def _current_project_name(root: Path, config: ScaffoldConfig) -> str:
    from agentscaffold.workspace_registry import load_registry, resolve_project_for_path

    hit = resolve_project_for_path(root, load_registry())
    if hit is not None:
        return hit.name
    name = getattr(getattr(config, "framework", None), "project_name", None)
    return str(name) if name else root.name


def _require_registered_project(name: str) -> Any:
    from agentscaffold.workspace_registry import find_registered_project_by_name

    hit = find_registered_project_by_name(name)
    if hit is None:
        raise ImplementationProjectError(
            f"implementation_project {name!r} is not a registered project name"
        )
    return hit


def _open_project_graph(project_root: Path) -> Any | None:
    from agentscaffold.graph import graph_available, open_graph

    try:
        cfg = load_config(find_config(start=project_root))
    except Exception:
        return None
    if not graph_available(cfg, start=project_root):
        return None
    try:
        return open_graph(cfg, read_only=True, start=project_root)
    except Exception:
        return None


def _is_absolute_or_home(rel: str) -> bool:
    if not rel:
        return False
    candidate = Path(rel)
    return candidate.is_absolute() or rel.startswith("~") or rel.startswith("/")


def _language_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".md": "markdown",
    }.get(suffix, "")
