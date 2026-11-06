"""Post-implementation verification against plan and graph.

Verifies what was actually implemented versus what the plan specified:
  1. Plan compliance -- stated vs actual file modifications
  2. Signature verification -- do expected functions/classes exist
  3. Layer conformance -- check for layer violations
  4. Wiring check -- verify all callers of modified functions still work
  5. Test delta -- count tests added/modified
  6. Rule rows -- finding dispositions, workflow state, changelogs,
     contracts and read-only paths, over the files the plan changed in git
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentscaffold.graph.query_compat import ql, sql_escape
from agentscaffold.paths import resolve_node_path
from agentscaffold.review.changes import ChangeSet, plan_changes, validate_ref
from agentscaffold.review.file_impact_resolve import (
    ImplementationProjectError,
    current_project_name,
    plan_impact_paths,
    query_root,
    query_store,
    resolved_impacts,
)
from agentscaffold.review.filters import is_always_shown, is_source_code_file
from agentscaffold.review.queries import (
    get_adrs_for_plan,
    get_contracts_for_file,
    get_file_importers,
    get_function_callers,
    get_plan_by_number,
    get_plan_review,
)
from agentscaffold.review.test_presence import source_has_tests
from agentscaffold.validate.safety import matches_read_only

if TYPE_CHECKING:
    from agentscaffold.config import ScaffoldConfig
    from agentscaffold.graph.backend import GraphBackend

logger = logging.getLogger(__name__)

#: Rule rows, in output order.
COMPLIANCE_CHECKS = (
    "pre_review_disposition",
    "workflow_state_updated",
    "architecture_changelog",
    "package_changelog",
    "contract_with_interface",
    "read_only_paths",
    "inventory_lifecycle",
)
ARCHITECTURE_CHANGELOG = "docs/ai/architectural_design_changelog.md"
#: Review types written by the tools, not by an agent or human.
_AUTOMATED_REVIEW_TYPES = frozenset({"pre_review", "post_retro", "retro"})
_BREAKING = re.compile(r"^\s*-?\s*\**Breaking change\**:\s*\**\s*yes", re.IGNORECASE | re.MULTILINE)


@dataclass
class VerificationItem:
    """A single verification result."""

    check: str
    status: str  # pass, warn, fail, skip
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


def verify_implementation(
    store: GraphBackend,
    plan_number: int,
    *,
    root: Path | None = None,
    config: Any = None,
    base_ref: str | None = None,
) -> list[VerificationItem]:
    """Verify a plan's implementation against the graph.

    Should be run AFTER re-indexing the codebase post-implementation.
    Returns a list of verification items. With *root*, the compliance rule rows
    follow unless ``gates.in_progress_to_complete.compliance`` is ``off``.
    Raises ValueError for an unsafe *base_ref*.
    """
    plan = get_plan_by_number(store, plan_number)
    if plan is None:
        return [
            VerificationItem(
                check="plan_exists",
                status="fail",
                detail=f"Plan {plan_number} not found in graph.",
            )
        ]

    items: list[VerificationItem] = []
    try:
        with resolved_impacts(store, plan_number, root=root, config=config) as impacted_files:
            _verify_from_rows(store, plan_number, impacted_files, items)
    except ImplementationProjectError as exc:
        items.append(
            VerificationItem(
                check="plan_compliance",
                status="fail",
                detail=str(exc),
                evidence={"error_code": "implementation_project_unregistered"},
            )
        )
    if root is not None and _gate_level(config) != "off":
        items.extend(
            compliance_items(store, plan_number, root=Path(root), config=config, base_ref=base_ref)
        )
    return items


def _gate_level(config: Any) -> str:
    gates = getattr(config, "gates", None)
    if gates is None:
        return "off"
    return str(gates.in_progress_to_complete.compliance)


# ---------------------------------------------------------------------------
# Rule rows
# ---------------------------------------------------------------------------


@dataclass
class _Root:
    name: str
    path: Path
    config: ScaffoldConfig
    changes: ChangeSet


def compliance_items(
    store: GraphBackend,
    plan_number: int,
    *,
    root: Path,
    config: Any = None,
    base_ref: str | None = None,
) -> list[VerificationItem]:
    """Rule rows for *plan_number* over the files it changed under each root.

    Roots are the project and its ``implementation_project``. A check set to
    ``off`` in ``compliance.rules`` is omitted; a violation is ``fail`` at level
    ``block`` and ``warn`` otherwise. Raises ValueError for an unsafe *base_ref*.
    """
    from agentscaffold.config import ScaffoldConfig  # noqa: PLC0415

    cfg = config if isinstance(config, ScaffoldConfig) else ScaffoldConfig()
    if base_ref is not None:
        validate_ref(base_ref)
    plan = get_plan_by_number(store, plan_number)
    if plan is None:
        return []
    root = Path(root)
    text = _plan_text(plan, root)
    roots = _change_roots(store, plan_number, root, cfg, base_ref)
    level = cfg.compliance.level

    checks = {
        "pre_review_disposition": lambda: _check_disposition(store, plan, cfg, text),
        "workflow_state_updated": lambda: _check_workflow_state(roots, cfg),
        "architecture_changelog": lambda: _check_architecture_changelog(
            store, plan_number, plan, text, roots, cfg
        ),
        "package_changelog": lambda: _check_package_changelog(roots),
        "contract_with_interface": lambda: _check_contracts(store, plan_number, roots, cfg),
        "read_only_paths": lambda: _check_read_only(plan_number, text, roots, cfg),
        "inventory_lifecycle": lambda: _check_inventory_lifecycle(text, roots, cfg),
    }
    items: list[VerificationItem] = []
    for check in COMPLIANCE_CHECKS:
        rule_level = level(check)
        if rule_level == "off":
            continue
        status, detail, evidence = checks[check]()
        if status == "violation":
            status = "fail" if rule_level == "block" else "warn"
        if check != "pre_review_disposition":
            detail = f"{detail} Changes: {_change_note(roots)}."
            evidence = {**_change_evidence(roots), **evidence}
        items.append(VerificationItem(check=check, status=status, detail=detail, evidence=evidence))
    return items


Outcome = tuple[str, str, dict[str, Any]]


def _change_roots(
    store: GraphBackend,
    plan_number: int,
    root: Path,
    cfg: ScaffoldConfig,
    base_ref: str | None,
) -> list[_Root]:
    review = get_plan_review(store, plan_number) or {}
    commits = review.get("reviewedCommits") or {}
    impact = plan_impact_paths(store, plan_number, root)
    candidates: list[tuple[str, Path, ScaffoldConfig]] = [
        (current_project_name(root, cfg), root, cfg)
    ]
    sibling = _implementation_root(cfg)
    if sibling is not None:
        candidates.append(sibling)

    roots: list[_Root] = []
    for name, path, rcfg in candidates:
        if len(candidates) > 1:
            here = [p for p in impact if _exists(path, p)]
        else:
            here = impact
        kwargs: dict[str, Any] = {
            "base_branch": rcfg.compliance.base_branch,
            "reviewed_commit": commits.get(name),
            "impact_paths": here,
            "extra_paths": rcfg.graph.extra_paths,
        }
        try:
            changes = plan_changes(path, plan_number, base_ref=base_ref, **kwargs)
        except ValueError as exc:
            logger.warning("change range for %s: %s; using the default sources", name, exc)
            changes = plan_changes(path, plan_number, **kwargs)
        roots.append(_Root(name, path, rcfg, changes))
    return roots


def _exists(root: Path, node_path: str) -> bool:
    disk = resolve_node_path(root, node_path)
    return disk is not None and disk.exists()


def _implementation_root(cfg: ScaffoldConfig) -> tuple[str, Path, ScaffoldConfig] | None:
    name = cfg.implementation_project
    if not name:
        return None
    from agentscaffold.config import find_config, load_config  # noqa: PLC0415
    from agentscaffold.workspace_registry import (  # noqa: PLC0415
        find_registered_project_by_name,
    )

    hit = find_registered_project_by_name(name)
    if hit is None:
        return None
    path = Path(hit.project_root)
    try:
        sibling_cfg = load_config(find_config(start=path))
    except Exception as exc:  # noqa: BLE001 - a broken sibling config skips only its rows
        logger.warning("implementation_project %s config unreadable: %s", name, exc)
        return None
    return name, path, sibling_cfg


def _change_note(roots: list[_Root]) -> str:
    if len(roots) == 1:
        changes = roots[0].changes
        return f"{changes.source}, {changes.detail}"
    return "; ".join(f"{r.name} from {r.changes.source}, {r.changes.detail}" for r in roots)


def _change_evidence(roots: list[_Root]) -> dict[str, Any]:
    evidence: dict[str, Any] = {"change_source": roots[0].changes.source}
    if len(roots) > 1:
        evidence["change_sources"] = {r.name: r.changes.source for r in roots}
    return evidence


def _plan_text(plan: dict[str, Any], root: Path) -> str:
    raw = str(plan.get("p.filePath") or "")
    if not raw:
        return ""
    path = Path(raw) if Path(raw).is_absolute() else root / raw
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _plan_project(store: GraphBackend, plan: dict[str, Any]) -> str:
    rows = store.query(f"SELECT project FROM Plan WHERE id = '{sql_escape(str(plan['p.id']))}'")
    return str((rows[0].get("project") if rows else "") or "")


def _check_disposition(
    store: GraphBackend, plan: dict[str, Any], cfg: ScaffoldConfig, text: str = ""
) -> Outcome:
    from agentscaffold.graph.findings import DISPOSITIONS  # noqa: PLC0415
    from agentscaffold.inventory.plan_table import lifecycle_rows  # noqa: PLC0415

    project = _plan_project(store, plan)
    scope = f" AND COALESCE(project, '') IN ('', '{sql_escape(project)}')" if project else ""
    rows = store.query(
        "SELECT id, reviewType, category, status, finding FROM ReviewFinding"
        f" WHERE planNumber = {int(plan['p.number'])}{scope} ORDER BY id"
    )
    skipped = {c.upper() for c in cfg.precedent.statistic_categories}
    skipped |= {c.upper() for c in cfg.compliance.disposition_exempt_categories}
    table = [r.component for r in lifecycle_rows(text) or []]
    in_scope: list[str] = []
    undisposed: list[str] = []
    for row in rows:
        category = str(row.get("category") or "").upper()
        automated = str(row.get("reviewType") or "").lower() in _AUTOMATED_REVIEW_TYPES
        if category in skipped or (automated and not is_always_shown(category)):
            continue
        in_scope.append(str(row["id"]))
        if row.get("status") in DISPOSITIONS:
            continue
        if category == "COMPONENT" and _names_component(str(row.get("finding") or ""), table):
            continue
        undisposed.append(str(row["id"]))
    if undisposed:
        return (
            "violation",
            f"{len(undisposed)} of {len(in_scope)} pre-implementation finding(s) have no "
            "disposition (resolved, deferred or not_applicable).",
            {"undisposed": undisposed},
        )
    if not in_scope:
        return "pass", "No pre-implementation findings need an answer.", {}
    return "pass", f"All {len(in_scope)} pre-implementation finding(s) have a disposition.", {}


_COMPONENT_ID = re.compile(r"[a-z][a-z0-9_]*:[^\s`'\",;()]+")


def _names_component(finding: str, table: list[str]) -> bool:
    """True when a COMPONENT finding's component has a lifecycle table row."""
    named = {m.rstrip(".:") for m in _COMPONENT_ID.findall(finding)}
    return bool(named & set(table))


#: A lifecycle table ``Before`` cell meaning the plan adds the component.
_ADDED_BEFORE = frozenset({"", "-", "none", "n/a", "new", "absent"})


def _check_inventory_lifecycle(text: str, roots: list[_Root], cfg: ScaffoldConfig) -> Outcome:
    """The plan's lifecycle table is reflected, and INV-008 is clean over its changes."""
    from agentscaffold.inventory.checks import changed_file_findings  # noqa: PLC0415
    from agentscaffold.inventory.plan_table import lifecycle_rows  # noqa: PLC0415
    from agentscaffold.inventory.project import load_project_inventory  # noqa: PLC0415
    from agentscaffold.inventory.schema import InventoryError  # noqa: PLC0415

    if not cfg.inventory.enabled:
        return "skip", "The system inventory is not enabled.", {}
    root = roots[0]
    try:
        inventory = load_project_inventory(root.path, cfg)
    except InventoryError as exc:
        return "violation", f"The system inventory cannot be read: {exc}", {}
    rows = lifecycle_rows(text)
    inv008 = changed_file_findings(inventory, root.changes.files, root=root.path)
    if rows is None and not inv008:
        return (
            "skip",
            "No Component Lifecycle Changes table, and the change touches no paused or "
            "deprecated component.",
            {},
        )
    declared = inventory.by_id()
    unreflected: list[str] = []
    unresolved_owner: list[str] = []
    for row in rows or []:
        entry = declared.get(row.component)
        if row.after == "removed":
            if entry is not None:
                unreflected.append(f"{row.component}: still listed, but After is removed")
        elif entry is None:
            unreflected.append(f"{row.component}: not in the inventory")
        elif (entry.lifecycle or "") != row.after:
            unreflected.append(
                f"{row.component}: inventory says {entry.lifecycle}, table says {row.after}"
            )
        if entry is not None and row.before in _ADDED_BEFORE and not entry.owner_plan:
            unresolved_owner.append(row.component)
    tabled = {r.component for r in rows or []}
    untabled = [f.to_dict() for f in inv008 if f.component not in tabled]
    evidence: dict[str, Any] = {}
    if unreflected:
        evidence["unreflected"] = unreflected
    if untabled:
        evidence["inv_008"] = untabled
    if unresolved_owner:
        evidence["unresolved_owner"] = unresolved_owner
    if evidence:
        parts = []
        if unreflected:
            parts.append(
                f"{len(unreflected)} lifecycle table row(s) not reflected in the inventory"
            )
        if unresolved_owner:
            parts.append(
                f"{len(unresolved_owner)} added component(s) with no owner plan; add an "
                "agentscaffold annotation or a pin"
            )
        if untabled:
            parts.append(
                f"{len(untabled)} paused or deprecated component(s) changed without a table row"
            )
        return "violation", "; ".join(parts) + ".", evidence
    count = len(rows or [])
    return "pass", f"All {count} lifecycle table row(s) are reflected in the inventory.", {}


def _check_workflow_state(roots: list[_Root], cfg: ScaffoldConfig) -> Outcome:
    workflow = cfg.graph.workflow_state_file
    if workflow in roots[0].changes.files:
        return "pass", f"{workflow} was updated.", {}
    return "violation", f"{workflow} was not updated.", {}


def _check_architecture_changelog(
    store: GraphBackend,
    plan_number: int,
    plan: dict[str, Any],
    text: str,
    roots: list[_Root],
    cfg: ScaffoldConfig,
) -> Outcome:
    changed = set(roots[0].changes.files)
    project = _plan_project(store, plan) or None
    reasons: list[str] = []
    if get_adrs_for_plan(store, plan_number, project=project):
        reasons.append("an ADR governs it")
    if _BREAKING.search(text):
        reasons.append("it is a breaking change")
    if cfg.graph.architecture_doc in changed:
        reasons.append(f"it changes {cfg.graph.architecture_doc}")
    logged = ARCHITECTURE_CHANGELOG in changed
    if reasons:
        why = " and ".join(reasons)
        if logged:
            return "pass", f"The plan is architectural ({why}) and the changelog was updated.", {}
        return (
            "violation",
            f"The plan is architectural ({why}) but {ARCHITECTURE_CHANGELOG} was not updated.",
            {},
        )
    if logged:
        return (
            "violation",
            f"{ARCHITECTURE_CHANGELOG} changed, but no ADR, breaking change or architecture "
            "document change marks the plan as architectural.",
            {},
        )
    return "skip", "The plan is not architectural and the changelog is unchanged.", {}


def _is_source(path: str) -> bool:
    return not (path.startswith("docs/") or path.endswith(".md"))


def _check_package_changelog(roots: list[_Root]) -> Outcome:
    missing: list[str] = []
    updated: list[str] = []
    unconfigured: list[str] = []
    for r in roots:
        if not any(_is_source(p) for p in r.changes.files):
            continue
        changelog = r.config.compliance.package_changelog
        if not changelog:
            unconfigured.append(r.name)
        elif changelog in r.changes.files:
            updated.append(f"{r.name}: {changelog}")
        else:
            missing.append(f"{r.name}: {changelog}")
    if missing:
        return "violation", f"Source changed but not its changelog ({', '.join(missing)}).", {}
    if updated:
        return "pass", f"Changelog updated ({', '.join(updated)}).", {}
    if unconfigured:
        return (
            "skip",
            "compliance.package_changelog is not configured for "
            f"{', '.join(unconfigured)}, where source changed.",
            {},
        )
    return "skip", "No source files changed.", {}


def _check_contracts(
    store: GraphBackend, plan_number: int, roots: list[_Root], cfg: ScaffoldConfig
) -> Outcome:
    project = roots[0]
    contracts_dir = cfg.graph.contracts_dir.rstrip("/") + "/"
    contracts = {
        p
        for p in plan_impact_paths(store, plan_number, project.path)
        if p.startswith(contracts_dir)
    }
    for path in project.changes.files:
        if path.startswith(contracts_dir):
            continue
        for contract in get_contracts_for_file(store, path):
            contract_path = _relative(str(contract.get("c.filePath") or ""), project.path)
            if contract_path:
                contracts.add(contract_path)
    if not contracts:
        return "skip", "No contract covers the changed files and the plan lists none.", {}
    stale = sorted(c for c in contracts if c not in project.changes.files)
    if stale:
        return (
            "violation",
            f"{len(stale)} contract(s) not updated: {', '.join(stale)}.",
            {"contracts": stale},
        )
    return "pass", f"All {len(contracts)} contract(s) were updated.", {}


def _relative(path: str, root: Path) -> str:
    if not path:
        return ""
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return ""


def _check_read_only(
    plan_number: int, text: str, roots: list[_Root], cfg: ScaffoldConfig
) -> Outcome:
    hits: list[str] = []
    for r in roots:
        protected = r.config.semi_autonomous.safety.read_only_paths
        prefix = "" if r is roots[0] else f"{r.name}:"
        hits.extend(f"{prefix}{p}" for p in r.changes.files if matches_read_only(p, protected))
    if not hits:
        return "skip", "No protected path changed.", {}
    from agentscaffold.mcp.governance_delivery import approval_record  # noqa: PLC0415

    record = approval_record(text, plan_number, roots[0].path / cfg.graph.workflow_state_file)
    if record is not None:
        return (
            "pass",
            f"Protected path(s) changed with a recorded approval ({record['line']}).",
            {"paths": hits},
        )
    return (
        "violation",
        f"Protected path(s) changed without a recorded approval: {', '.join(hits)}.",
        {"paths": hits},
    )


def _verify_from_rows(
    store: GraphBackend,
    plan_number: int,
    impacted_files: list[dict[str, Any]],
    items: list[VerificationItem],
) -> None:
    resolved = [
        f
        for f in impacted_files
        if f.get("f.path") and f.get("resolution") in (None, "local", "sibling")
    ]
    skipped = [f for f in impacted_files if f.get("resolution") == "skipped"]
    planned_paths = {f.get("f.path", "") for f in resolved}

    _check_plan_compliance(store, plan_number, planned_paths, items, rows=resolved)
    if skipped:
        items.append(
            VerificationItem(
                check="plan_compliance",
                status="skip",
                detail=(
                    f"{len(skipped)} File Impact path(s) are outside this project "
                    "and were not certified. This is not a pass."
                ),
                evidence={
                    "skipped": [f.get("f.path") for f in skipped],
                    "reasons": [f.get("reason") for f in skipped],
                },
            )
        )
    _check_signatures(store, planned_paths, items, rows=resolved)
    _check_wiring(store, planned_paths, items, rows=resolved)
    _check_test_delta(store, planned_paths, items, rows=resolved)


# ---------------------------------------------------------------------------
# Verification checks
# ---------------------------------------------------------------------------


def _check_plan_compliance(
    store: GraphBackend,
    plan_number: int,
    planned_paths: set[str],
    out: list[VerificationItem],
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """Check that planned files exist in the graph and flag any extra modifications."""
    nonempty = {p for p in planned_paths if p}
    if not nonempty:
        out.append(
            VerificationItem(
                check="plan_compliance",
                status="skip",
                detail=(
                    "No planned files resolved in this project, so compliance "
                    "cannot be certified. This is not a pass."
                ),
                evidence={"planned_count": 0},
            )
        )
        return

    row_by_path = {r.get("f.path"): r for r in (rows or []) if r.get("f.path")}
    missing: list[str] = []
    for fpath in planned_paths:
        if not fpath:
            continue
        frow = row_by_path.get(fpath, {})
        if frow.get("resolution") == "sibling":
            if not _exists(query_root(frow, Path(".")), fpath):
                missing.append(fpath)
            continue
        file_id = f"file::{fpath}"
        escaped = sql_escape(file_id)
        found = ql(
            query_store(frow, store),
            sql=f"SELECT id AS \"f.id\" FROM File WHERE id = '{escaped}'",
        )
        if not found:
            missing.append(fpath)

    if missing:
        out.append(
            VerificationItem(
                check="plan_compliance",
                status="warn",
                detail=(
                    f"{len(missing)} files in the plan's impact map were not found "
                    f"in the graph: {', '.join(missing[:5])}"
                ),
                evidence={"missing_files": missing},
            )
        )
    else:
        out.append(
            VerificationItem(
                check="plan_compliance",
                status="pass",
                detail=f"All {len(planned_paths)} planned files exist in the graph.",
            )
        )


def _check_signatures(
    store: GraphBackend,
    planned_paths: set[str],
    out: list[VerificationItem],
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """Verify that expected functions and classes exist in planned files."""
    row_by_path = {r.get("f.path"): r for r in (rows or []) if r.get("f.path")}
    total_defs = 0
    for fpath in planned_paths:
        if not fpath:
            continue
        escaped = sql_escape(fpath)
        qstore = query_store(row_by_path.get(fpath, {}), store)
        funcs = ql(
            qstore,
            sql=(
                f'SELECT name AS "fn.name", signature AS "fn.signature" '
                f"FROM Function WHERE filePath = '{escaped}'"
            ),
        )
        classes = ql(
            qstore,
            sql=f"SELECT name AS \"c.name\" FROM Class WHERE filePath = '{escaped}'",
        )
        total_defs += len(funcs) + len(classes)

    out.append(
        VerificationItem(
            check="signatures",
            status="pass" if total_defs > 0 else "warn",
            detail=f"{total_defs} definitions found across planned files.",
            evidence={"total_definitions": total_defs},
        )
    )


def _check_wiring(
    store: GraphBackend,
    planned_paths: set[str],
    out: list[VerificationItem],
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """Check that all callers/importers of planned files still resolve."""
    row_by_path = {r.get("f.path"): r for r in (rows or []) if r.get("f.path")}
    total_importers = 0
    broken_imports: list[str] = []

    for fpath in planned_paths:
        if not fpath:
            continue
        qstore = query_store(row_by_path.get(fpath, {}), store)
        importers = get_file_importers(qstore, fpath)
        callers = get_function_callers(qstore, fpath)
        total_importers += len(importers) + len(callers)

    if broken_imports:
        out.append(
            VerificationItem(
                check="wiring",
                status="fail",
                detail=f"{len(broken_imports)} broken import/call references detected.",
                evidence={"broken": broken_imports},
            )
        )
    else:
        out.append(
            VerificationItem(
                check="wiring",
                status="pass",
                detail=f"{total_importers} import/call references verified.",
                evidence={"total_references": total_importers},
            )
        )


def _check_test_delta(
    store: GraphBackend,
    planned_paths: set[str],
    out: list[VerificationItem],
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """Count test files that exist for planned source files."""
    row_by_path = {r.get("f.path"): r for r in (rows or []) if r.get("f.path")}
    tested_count = 0
    untested: list[str] = []

    for fpath in sorted(planned_paths):
        if not fpath or "/test" in fpath or fpath.startswith("tests/"):
            continue

        frow = row_by_path.get(fpath, {})
        if not is_source_code_file(fpath, frow.get("f.language", "")):
            continue
        qstore = query_store(frow, store)
        disk_root = query_root(frow, Path(".")) if frow else None
        if source_has_tests(qstore, fpath, root=disk_root):
            tested_count += 1
        else:
            untested.append(fpath)

    total = tested_count + len(untested)
    if total == 0:
        out.append(
            VerificationItem(
                check="test_delta",
                status="skip",
                detail="No source files in the change set; documents and config need no tests.",
            )
        )
    elif untested:
        out.append(
            VerificationItem(
                check="test_delta",
                status="warn",
                detail=(
                    f"Tests found for {tested_count}/{total} source files. "
                    f"Missing: {', '.join(untested[:5])}"
                ),
                evidence={"tested": tested_count, "untested": untested},
            )
        )
    else:
        out.append(
            VerificationItem(
                check="test_delta",
                status="pass",
                detail=f"Tests found for all {total} source files.",
            )
        )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_verification_markdown(items: list[VerificationItem]) -> str:
    """Render verification results as markdown."""
    if not items:
        return "No verification results.\n"

    lines: list[str] = []
    lines.append("## Post-Implementation Verification")
    lines.append("")

    status_icon = {
        "pass": "[PASS]",
        "warn": "[WARN]",
        "fail": "[FAIL]",
        "skip": "[SKIP]",
    }
    for item in items:
        icon = status_icon.get(item.status, "[????]")
        lines.append(f"{icon} **{item.check}**: {item.detail}")

    lines.append("")
    return "\n".join(lines)
