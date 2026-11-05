"""INV-001..INV-010 (contract v1, Checks) and enforcement.

Severity is part of a check's meaning: INV-007 to INV-009 are warnings, the
rest are errors. The mode decides only the exit code: ``warn`` always exits 0;
``fail`` exits non-zero when an error is present.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agentscaffold.inventory import paths as inv_paths
from agentscaffold.inventory.collectors import CollectionResult
from agentscaffold.inventory.schema import DORMANT, LIFECYCLES, Component, Inventory

WARNING_CHECKS = frozenset({"INV-007", "INV-008", "INV-009"})
_ID = re.compile(r"^([a-z][a-z0-9_]*):(\S+)$")
_PLAN_FILE = re.compile(r"^(\d+)[-_.]")
_ALWAYS_REQUIRED = (
    "id",
    "kind",
    "name",
    "layer",
    "owner_plan",
    "roadmap_stage",
    "lifecycle",
    "since",
)
_EXPLAINED = frozenset({"experimental", "paused", "deprecated"})
_EXIT_CRITERIA = frozenset({"experimental", "paused"})
_ENTRYPOINT_KINDS = frozenset({"scheduled_job", "manual_job", "service", "app"})


@dataclass
class Finding:
    """One check result, in the contract's JSON shape."""

    id: str
    severity: str
    component: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finding(check: str, component: str | None, message: str) -> Finding:
    return Finding(check, "warning" if check in WARNING_CHECKS else "error", component, message)


def effective_mode(enforcement: str, warn_until: str | None, today: dt.date) -> str:
    """``warn`` turns into ``fail`` once *warn_until* has passed."""
    if enforcement == "warn" and warn_until:
        try:
            if today > dt.date.fromisoformat(warn_until):
                return "fail"
        except ValueError:
            pass
    return enforcement


def exit_code(findings: list[Finding], mode: str) -> int:
    if mode != "fail":
        return 0
    return 1 if any(f.severity == "error" for f in findings) else 0


def plan_numbers(plans_dir: Path) -> set[int]:
    """Plan numbers that have a file in *plans_dir* (``080-name.md`` is 80)."""
    numbers: set[int] = set()
    if not plans_dir.is_dir():
        return numbers
    for path in plans_dir.glob("*.md"):
        match = _PLAN_FILE.match(path.name)
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def _stage(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    try:
        return tuple(int(part) for part in str(value).split("."))
    except ValueError:
        return None


def _invalid_paths(component: Component) -> list[str]:
    bad: list[str] = []
    if component.source and inv_paths.path_problem(component.source):
        bad.append("source")
    file_part = inv_paths.entrypoint_path(component.entrypoint)
    if file_part and inv_paths.path_problem(file_part):
        bad.append("entrypoint")
    if any(inv_paths.path_problem(r) for r in component.reads):
        bad.append("reads")
    return bad


def _missing_fields(component: Component, collected_kinds: set[str]) -> list[str]:
    lifecycle = component.lifecycle or ""
    missing = [f for f in _ALWAYS_REQUIRED if not getattr(component, f)]
    if component.kind in collected_kinds and not component.source:
        missing.append("source")
    if component.kind in _ENTRYPOINT_KINDS and not component.entrypoint:
        missing.append("entrypoint")
    if lifecycle in _EXPLAINED:
        missing += [f for f in ("reason", "review_by") if not getattr(component, f)]
    if lifecycle in _EXIT_CRITERIA and not component.exit_criteria:
        missing.append("exit_criteria")
    if lifecycle == "deprecated" and not component.declared("replaced_by"):
        missing.append("replaced_by")
    return missing


def check_required(component: Component, collected_kinds: set[str]) -> Finding | None:
    """INV-003: required fields for the entry's lifecycle, valid dates and paths."""
    problems: list[str] = []
    missing = _missing_fields(component, collected_kinds)
    if missing:
        problems.append("missing " + ", ".join(missing))
    if component.lifecycle and component.lifecycle not in LIFECYCLES:
        problems.append(f"lifecycle {component.lifecycle!r} is not one of {', '.join(LIFECYCLES)}")
    for field_name in ("since", "review_by"):
        if getattr(component, field_name) and getattr(component, f"{field_name}_date") is None:
            problems.append(f"{field_name} is not a YYYY-MM-DD date")
    invalid = _invalid_paths(component)
    if invalid:
        problems.append("invalid path in " + ", ".join(invalid))
    if not problems:
        return None
    return _finding("INV-003", component.id, "; ".join(problems))


def run_checks(
    inventory: Inventory,
    collected: CollectionResult,
    *,
    root: Path,
    plans_dir: Path,
    today: dt.date,
    changed_files: Iterable[str] | None = None,
) -> list[Finding]:
    """Every finding for *inventory*, in check order."""
    findings: list[Finding] = []
    declared = inventory.by_id()
    found = collected.by_id()

    for comp in collected.components:
        if comp.id not in declared:
            findings.append(
                _finding(
                    "INV-001",
                    comp.id,
                    f"{comp.source} declares {comp.kind} {comp.name!r}"
                    " but the inventory has no entry",
                )
            )

    for entry in inventory.components:
        prefix = (entry.id or "").split(":", 1)[0]
        if prefix in collected.collectors and entry.id not in found:
            findings.append(
                _finding(
                    "INV-002", entry.id, f"no {prefix} source declares {entry.id} (ghost entry)"
                )
            )

    for entry in inventory.components:
        required = check_required(entry, collected.kinds)
        if required is not None:
            findings.append(required)

    for entry in inventory.components:
        review_by = entry.review_by_date
        if review_by is not None and review_by < today:
            findings.append(_finding("INV-004", entry.id, f"review_by {review_by} has passed"))

    numbers = plan_numbers(plans_dir)
    for entry in inventory.components:
        if not entry.owner_plan:
            continue
        try:
            owner = int(entry.owner_plan)
        except ValueError:
            owner = None
        if owner is None or owner not in numbers:
            findings.append(
                _finding("INV-005", entry.id, f"owner_plan {entry.owner_plan} names no plan file")
            )

    findings.extend(_duplicate_jobs(inventory, found))

    current = _stage(inventory.current_roadmap_stage)
    for entry in inventory.components:
        stage = _stage(entry.roadmap_stage)
        if entry.lifecycle == "active" and current and stage and stage > current:
            findings.append(
                _finding(
                    "INV-007",
                    entry.id,
                    f"active but needed only from roadmap stage {entry.roadmap_stage} "
                    f"(current stage {inventory.current_roadmap_stage})",
                )
            )

    if changed_files is not None:
        findings.extend(changed_file_findings(inventory, changed_files, root=root))

    findings.extend(_review_cadence(inventory, today))
    findings.extend(_ids(inventory))
    return findings


def _duplicate_jobs(inventory: Inventory, found: dict[str, Any]) -> list[Finding]:
    """INV-006: scheduled jobs sharing an entrypoint and parameters."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry in inventory.components:
        if entry.kind != "scheduled_job" or not entry.id:
            continue
        hit = found.get(entry.id)
        entrypoint = (hit.entrypoint if hit and hit.entrypoint else entry.entrypoint) or ""
        if not entrypoint:
            continue
        params = hit.parameters_key() if hit else "{}"
        groups[(entrypoint, params)].append(entry.id)
    out: list[Finding] = []
    for (entrypoint, _params), ids in groups.items():
        if len(ids) > 1:
            out.append(
                _finding(
                    "INV-006",
                    ids[0],
                    f"scheduled jobs {', '.join(ids)} share entrypoint {entrypoint} and parameters",
                )
            )
    return out


def dormant_hits(
    inventory: Inventory, paths: Iterable[str], *, root: Path
) -> list[tuple[Component, list[str]]]:
    """Paused or deprecated components whose ``reads`` or entrypoint *paths* touch.

    The INV-008 rule. *paths* are project-relative or ``@repo/`` paths; a
    directory ends with ``/``. Each component appears once with the paths that
    touched it.
    """
    wanted = [p for p in (inv_paths.graph_path(root, p) for p in paths) if p is not None]
    hits: list[tuple[Component, list[str]]] = []
    for entry in inventory.components:
        if entry.lifecycle not in DORMANT:
            continue
        declared = list(entry.reads)
        file_part = inv_paths.entrypoint_path(entry.entrypoint)
        if file_part:
            declared.append(file_part)
        targets = [t for t in (inv_paths.graph_path(root, d) for d in declared) if t is not None]
        touched = sorted({p for p in wanted for t in targets if inv_paths.touches(t, p)})
        if touched:
            hits.append((entry, touched))
    return hits


def changed_file_findings(
    inventory: Inventory, changed_files: Iterable[str], *, root: Path
) -> list[Finding]:
    """INV-008 over a change's files."""
    return [
        _finding(
            "INV-008",
            entry.id,
            f"{entry.lifecycle} component; this change edits {', '.join(touched[:5])}"
            + (f" and {len(touched) - 5} more" if len(touched) > 5 else ""),
        )
        for entry, touched in dormant_hits(inventory, changed_files, root=root)
    ]


def _review_cadence(inventory: Inventory, today: dt.date) -> list[Finding]:
    """INV-009: the architecture review is overdue by more than five days."""
    last = inventory.last_review_date
    limit = inventory.review_cadence_days + 5
    if last is None:
        return [_finding("INV-009", None, "last_architecture_review is not recorded")]
    if (today - last).days > limit:
        return [
            _finding(
                "INV-009",
                None,
                f"last_architecture_review {last} is older than {limit} days",
            )
        ]
    return []


def _ids(inventory: Inventory) -> list[Finding]:
    """INV-010: ids are unique and are ``<prefix>:<name>``."""
    out: list[Finding] = []
    seen: dict[str, int] = defaultdict(int)
    for entry in inventory.components:
        if entry.id:
            seen[entry.id] += 1
    for entry_id, count in seen.items():
        if count > 1:
            out.append(_finding("INV-010", entry_id, f"id {entry_id} appears {count} times"))
    for entry in inventory.components:
        if not entry.id:
            continue
        match = _ID.match(entry.id)
        if match is None:
            out.append(_finding("INV-010", entry.id, f"id {entry.id!r} is not <prefix>:<name>"))
        elif entry.name and match.group(2) != entry.name:
            out.append(
                _finding(
                    "INV-010", entry.id, f"id {entry.id} does not end with name {entry.name!r}"
                )
            )
    return out


def broad_reads(
    inventory: Inventory, files: list[str], *, root: Path, share: float
) -> list[dict[str, Any]]:
    """``reads`` entries that name the project root or cover more than *share* of *files*.

    An over-broad ``reads`` makes every plan touch the component, which turns the
    component challenge into noise. AgentScaffold-only; not a contract check.
    """
    out: list[dict[str, Any]] = []
    total = len(files)
    for entry in inventory.components:
        for read in entry.reads:
            target = inv_paths.graph_path(root, read)
            if target is None:
                continue
            covered = sum(1 for f in files if inv_paths.covers(target, f))
            if target in ("", "/") or (total and covered / total > share):
                out.append(
                    {
                        "component": entry.id,
                        "read": read,
                        "covered_files": covered,
                        "total_files": total,
                        "message": (
                            f"{entry.id} reads {read!r}, which covers {covered} of {total} "
                            "indexed files; narrow it so the component challenge stays specific"
                        ),
                    }
                )
    return out


def summary(inventory: Inventory, findings: list[Finding]) -> dict[str, int]:
    return {
        "components": len(inventory.components),
        "errors": sum(1 for f in findings if f.severity == "error"),
        "warnings": sum(1 for f in findings if f.severity == "warning"),
    }
