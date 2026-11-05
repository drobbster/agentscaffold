"""Plan linting and cohesion checks."""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from agentscaffold.config import ScaffoldConfig, load_config
from agentscaffold.paths import ResolvedPaths, resolve_root

console = Console()

REQUIRED_SECTIONS: list[tuple[str, ...]] = [
    # "Bug Description" is the bugfix template's name for this slot -- a bugfix
    # plan states what is broken where a feature plan states what success means.
    # Without the alias the linter demanded a heading that template does not
    # have, so every correctly-written bugfix plan failed the Draft -> Review
    # gate that AGENTS.md requires it to pass.
    ("Objective", "Goal", "Purpose", "Bug Description"),
    ("File Impact Map", "Files Changed", "Impact"),
    ("Execution Steps", "Steps", "Implementation"),
    ("Tests", "Test Plan", "Testing"),
    ("Validation Commands", "Validation"),
    ("Rollback Plan", "Rollback"),
]

HEADING_RE = re.compile(r"^#{1,4}\s+(?:\d+\.\s*)?(.+)", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^-\s+\[[ xX]\]\s+", re.MULTILINE)
FILE_REF_RE = re.compile(r"\|\s*`?\S+\.\w+`?\s*\|")
TEST_FILE_RE = re.compile(r"test[_s]?\S*\.py|\.test\.\w+|_test\.\w+|spec\.\w+")


def _extract_headings(text: str) -> list[str]:
    return [m.group(1).strip() for m in HEADING_RE.finditer(text)]


def _has_section(headings: list[str], aliases: tuple[str, ...]) -> bool:
    lowered = [h.lower() for h in headings]
    return any(alias.lower() in lowered for alias in aliases)


def _lint_plan(
    path: Path, config: ScaffoldConfig | None = None, root: Path | None = None
) -> list[str]:
    """Return a list of issue strings for a single plan file.

    With *config* and an enabled inventory, the inventory field checks run too.
    """
    issues: list[str] = []
    text = path.read_text()
    headings = _extract_headings(text)

    has_yaml_front = text.startswith("---")
    has_metadata_heading = any("metadata" in h.lower() for h in headings)
    if not has_yaml_front and not has_metadata_heading:
        issues.append("Missing metadata section (## Metadata or YAML frontmatter)")

    for aliases in REQUIRED_SECTIONS:
        if not _has_section(headings, aliases):
            issues.append(f"Missing required section: {aliases[0]}")

    if not CHECKBOX_RE.search(text):
        issues.append("Execution steps should use checkbox format (- [ ] or - [x])")

    if not FILE_REF_RE.search(text):
        issues.append("File Impact Map should list at least one file")

    if not TEST_FILE_RE.search(text):
        issues.append("Tests section should reference at least one test file")

    if config is not None and config.inventory.enabled:
        issues.extend(_lint_inventory_fields(text, config, root or resolve_root()))

    return issues


COMPONENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*:[A-Za-z0-9_.\-/]+$")
_NEW = frozenset({"new", "(new)", "none", "-", ""})
_CLOSED = frozenset({"Complete", "Superseded"})


def _lint_inventory_fields(text: str, config: ScaffoldConfig, root: Path) -> list[str]:
    """Status vocabulary, adoption-date fields and component ids.

    Applies only with the inventory enabled, so projects that upgrade without
    opting in see no new lint failures.
    """
    from agentscaffold.graph.governance import _extract_metadata
    from agentscaffold.inventory.plan_table import (
        has_components_line,
        lifecycle_rows,
        plan_components,
    )
    from agentscaffold.inventory.project import maybe_inventory
    from agentscaffold.plan.status import status_lines
    from agentscaffold.review.filters import normalize_plan_status

    issues: list[str] = []
    statuses = status_lines(text)
    if len(statuses) > 1:
        issues.append(f"Plan has {len(statuses)} Status lines; keep one")
    for raw in statuses:
        if normalize_plan_status(raw) == "Unknown":
            issues.append(
                f"Status '{raw}' is not one of Draft, Review, Ready, In Progress, Complete, "
                "Superseded (run `scaffold plan normalize-status`)"
            )

    meta = _extract_metadata(text)
    adoption = _date(str(config.inventory.plan_adoption_date or ""))
    created = _date(meta.get("created", meta.get("date", "")))
    if adoption is not None and created is not None and created >= adoption:
        if not statuses:
            issues.append("Missing '- Status:' line (required from the inventory adoption date)")
        if "roadmap_stage" not in meta:
            issues.append("Missing '- Roadmap Stage:' line (required from the adoption date)")
        if not has_components_line(text):
            issues.append("Missing '- Components:' line (required from the adoption date)")
        if lifecycle_rows(text) is None:
            issues.append(
                "Missing 'Component Lifecycle Changes' table (required from the adoption date)"
            )

    rows = lifecycle_rows(text) or []
    named = plan_components(text) + [r.component for r in rows]
    malformed = sorted({c for c in named if not COMPONENT_ID_RE.match(c)})
    issues.extend(f"Component id '{c}' is not <kind-prefix>:<name>" for c in malformed)

    status = normalize_plan_status(statuses[0]) if statuses else "Unknown"
    inventory = maybe_inventory(root, config) if status not in _CLOSED else None
    if inventory is not None:
        declared = set(inventory.by_id())
        introduced = {r.component for r in rows if r.before in _NEW}
        unknown = sorted(
            {c for c in named if c not in declared and c not in introduced} - set(malformed)
        )
        issues.extend(
            f"Component '{c}' is not in {config.inventory.path} (a new one needs a "
            "Component Lifecycle Changes row with Before 'new')"
            for c in unknown
        )
    return issues


def _date(value: str) -> dt.date | None:
    match = re.search(r"\d{4}-\d{2}-\d{2}", value or "")
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(0))
    except ValueError:
        return None


def run_plan_lint(plan: str | None) -> None:
    """Lint a plan file for cohesion and template compliance."""
    config = load_config()
    root = resolve_root()
    plans_dir = ResolvedPaths(config, root).plans_dir

    if not plans_dir.is_dir():
        console.print(f"[yellow]Warning: {plans_dir} does not exist. Nothing to lint.[/yellow]")
        return

    if plan is not None:
        candidates = list(plans_dir.glob(f"*{plan}*"))
        if not candidates:
            console.print(f"[red]No plan matching '{plan}' found in {plans_dir}[/red]")
            raise SystemExit(1)
        plan_files = sorted(candidates)
    else:
        plan_files = sorted(plans_dir.glob("*.md"))

    if not plan_files:
        console.print("[yellow]No plan files found.[/yellow]")
        return

    table = Table(title="Plan Lint Results")
    table.add_column("Plan", style="cyan")
    table.add_column("Status")
    table.add_column("Issues")

    any_failure = False
    for pf in plan_files:
        issues = _lint_plan(pf, config, root)
        if issues:
            any_failure = True
            table.add_row(pf.name, "[red]FAIL[/red]", "\n".join(issues))
        else:
            table.add_row(pf.name, "[green]PASS[/green]", "")

    console.print(table)

    if any_failure:
        sys.exit(1)
