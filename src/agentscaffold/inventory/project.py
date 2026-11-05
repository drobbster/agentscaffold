"""The inventory of one project: its configuration, file, collectors and checks.

The CLI, ``scaffold validate``, orient and the reviews all go through here, so
they agree on what the inventory says.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentscaffold.domain_packs.loader import domain_inventory_collectors
from agentscaffold.inventory import checks
from agentscaffold.inventory.collectors import CollectionResult, collect
from agentscaffold.inventory.schema import Inventory, InventoryError, load_inventory


@dataclass
class CheckReport:
    """``scaffold inventory check`` output (contract JSON, plus agentscaffold notices)."""

    mode: str
    inventory: Inventory
    findings: list[checks.Finding]
    notices: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return checks.exit_code(self.findings, self.mode)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": 1,
            "mode": self.mode,
            "findings": [f.to_dict() for f in self.findings],
            "summary": checks.summary(self.inventory, self.findings),
        }
        if self.notices:
            out["notices"] = self.notices
        if self.problems:
            out["problems"] = self.problems
        return out


def inventory_path(root: Path, config: Any) -> Path:
    return Path(root) / str(config.inventory.path)


def collectors_of(config: Any) -> list[tuple[str, list[str]]]:
    """Configured collectors; without an explicit list, the defaults plus the domain packs'."""
    out = [(c.name, list(c.sources)) for c in config.inventory.collectors]
    if "collectors" in getattr(config.inventory, "model_fields_set", {"collectors"}):
        return out
    names = {name for name, _ in out}
    for name in domain_inventory_collectors(list(getattr(config, "domains", []) or [])):
        if name not in names:
            out.append((name, []))
            names.add(name)
    return out


def run_collectors(root: Path, config: Any) -> CollectionResult:
    return collect(Path(root), collectors_of(config))


def load_project_inventory(root: Path, config: Any) -> Inventory:
    """The project's inventory. Raises InventoryError when absent or malformed."""
    return load_inventory(inventory_path(root, config))


def maybe_inventory(root: Path | None, config: Any) -> Inventory | None:
    """The inventory when enabled and readable, else None. Never raises."""
    if root is None or config is None or not getattr(config, "inventory", None):
        return None
    if not config.inventory.enabled:
        return None
    try:
        return load_project_inventory(Path(root), config)
    except InventoryError:
        return None


def indexed_files(root: Path, config: Any) -> list[str]:
    """Files the indexer would consider, for the broad-``reads`` share."""
    try:
        from agentscaffold.graph.source_roots import extra_path_files  # noqa: PLC0415
        from agentscaffold.graph.structure import (  # noqa: PLC0415
            collect_ignore_patterns,
            scan_indexable_files,
        )
    except ImportError:
        return []
    graph_config = getattr(config, "graph", None)
    files = scan_indexable_files(Path(root), collect_ignore_patterns(Path(root), graph_config))
    files.extend(extra_path_files(Path(root), graph_config, None))
    return files


def check_project(
    root: Path,
    config: Any,
    *,
    today: dt.date | None = None,
    changed_files: list[str] | None = None,
    files: list[str] | None = None,
) -> CheckReport:
    """Run every check. Raises InventoryError when the inventory cannot be read."""
    root = Path(root)
    today = today or dt.date.today()
    inv_cfg = config.inventory
    inventory = load_project_inventory(root, config)
    collected = run_collectors(root, config)
    plans_dir = root / config.graph.plans_dir
    findings = checks.run_checks(
        inventory,
        collected,
        root=root,
        plans_dir=plans_dir,
        today=today,
        changed_files=changed_files,
    )
    scan = files if files is not None else indexed_files(root, config)
    notices = checks.broad_reads(inventory, scan, root=root, share=inv_cfg.broad_reads_share)
    mode = checks.effective_mode(inv_cfg.enforcement, inv_cfg.warn_until, today)
    return CheckReport(
        mode=mode,
        inventory=inventory,
        findings=findings,
        notices=notices,
        problems=list(collected.problems),
    )
