"""``scaffold plan normalize-status``: propose and apply plan Status lines.

A plan with one valid Status line (any line ``normalize_plan_status`` maps to a
known status, qualified lines included) is left alone. A plan with no Status
line gets one proposed from its execution-step checkboxes when they decide it:
all checked is Complete, some checked is In Progress. Everything else (no steps
checked, two Status lines, a Status outside the vocabulary, no metadata section
to add the line to) is listed as ambiguous for a human to decide. Nothing is
written without ``--apply``, and ambiguous plans are never written.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from agentscaffold.plan.status import CHECKBOX_DONE_RE, CHECKBOX_TOTAL_RE, status_lines
from agentscaffold.review.filters import normalize_plan_status

_METADATA_HEADING = re.compile(r"^#{1,4}\s+(?:\d+\.\s*)?Metadata\b", re.IGNORECASE)
_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}")
_FIELD_TABLE_HEADER = re.compile(r"^\|\s*(?:Field|Key)\s*\|\s*Value\s*\|", re.IGNORECASE)
_HEADER_LINES = 80


@dataclass(frozen=True)
class StatusProposal:
    plan: str
    current: str
    proposed: str | None
    reason: str

    @property
    def ambiguous(self) -> bool:
        return self.proposed is None


def propose(text: str) -> tuple[str | None, str, str] | None:
    """``(proposed, current, reason)`` for a plan, or None when it needs nothing."""
    lines = status_lines(text)
    if len(lines) > 1:
        return None, " / ".join(lines), f"{len(lines)} Status lines; keep one"
    if lines:
        if normalize_plan_status(lines[0]) != "Unknown":
            return None
        return None, lines[0], "Status is not in the vocabulary; choose one"
    total = len(CHECKBOX_TOTAL_RE.findall(text))
    done = len(CHECKBOX_DONE_RE.findall(text))
    if total and done == total:
        return "Complete", "", f"all {total} steps checked"
    if done:
        return "In Progress", "", f"{done} of {total} steps checked"
    if total:
        return None, "", f"no steps checked of {total}: Draft, Review or Ready"
    return None, "", "no execution steps: Draft or Superseded"


def insert_status(text: str, status: str) -> str | None:
    """*text* with a Status line in its metadata; None when there is nowhere to put it."""
    lines = text.splitlines(keepends=True)
    head = lines[:_HEADER_LINES]
    for index, line in enumerate(head):
        if _METADATA_HEADING.match(line.strip()):
            return _insert_after_heading(lines, index, status)
    for index, line in enumerate(head):
        if _FIELD_TABLE_HEADER.match(line.strip()):
            return _insert_table_row(lines, index, status)
    return None


def _insert_after_heading(lines: list[str], heading: int, status: str) -> str | None:
    for index in range(heading + 1, min(len(lines), heading + _HEADER_LINES)):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if stripped.startswith("|"):
            return _insert_table_row(lines, index, status)
        if stripped.startswith("- "):
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            return _join(lines, index, f"{indent}- Status: {status}\n")
        break
    return _join(lines, heading + 1, f"- Status: {status}\n")


def _insert_table_row(lines: list[str], header: int, status: str) -> str | None:
    separator = header + 1
    if separator >= len(lines) or not _TABLE_SEPARATOR.match(lines[separator].strip()):
        return None
    return _join(lines, separator + 1, f"| Status | {status} |\n")


def _join(lines: list[str], index: int, new: str) -> str:
    if index > 0 and not lines[index - 1].endswith("\n"):
        lines[index - 1] += "\n"
    return "".join(lines[:index] + [new] + lines[index:])


def collect(plans_dir: Path, plan: str | None = None) -> list[StatusProposal]:
    """Proposals for every plan (or those matching *plan*) that needs a Status line."""
    pattern = f"*{plan}*" if plan else "*.md"
    out: list[StatusProposal] = []
    for path in sorted(plans_dir.glob(pattern)):
        if path.suffix != ".md" or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = propose(text)
        if found is None:
            continue
        proposed, current, reason = found
        if proposed is not None and insert_status(text, proposed) is None:
            proposed, reason = None, f"{reason}; no metadata section to add the line to"
        out.append(StatusProposal(path.name, current, proposed, reason))
    return out


def apply(plans_dir: Path, proposals: list[StatusProposal]) -> list[str]:
    """Write every unambiguous proposal; return the plan file names written."""
    written: list[str] = []
    for item in proposals:
        if item.proposed is None:
            continue
        path = plans_dir / item.plan
        updated = insert_status(path.read_text(encoding="utf-8"), item.proposed)
        if updated is not None:
            path.write_text(updated, encoding="utf-8")
            written.append(item.plan)
    return written


def run_normalize_status(
    plans_dir: Path,
    *,
    plan: str | None = None,
    write: bool = False,
    output: str = "text",
    console: Console | None = None,
) -> int:
    """CLI body. Exit code 0; 2 when the plans directory is missing."""
    console = console or Console()
    if not plans_dir.is_dir():
        console.print(f"[red]No plans directory at {plans_dir}[/red]")
        return 2
    proposals = collect(plans_dir, plan)
    written = apply(plans_dir, proposals) if write else []
    if output == "json":
        print(
            json.dumps(
                {
                    "applied": write,
                    "proposals": [asdict(p) for p in proposals if not p.ambiguous],
                    "ambiguous": [asdict(p) for p in proposals if p.ambiguous],
                    "written": written,
                },
                indent=2,
            )
        )
        return 0
    confident = [p for p in proposals if not p.ambiguous]
    ambiguous = [p for p in proposals if p.ambiguous]
    if not proposals:
        console.print("[green]Every plan has one valid Status line.[/green]")
        return 0
    if confident:
        table = Table(title="Proposed Status lines" + ("" if write else " (dry run)"))
        table.add_column("Plan", style="cyan")
        table.add_column("Proposed")
        table.add_column("Evidence")
        for p in confident:
            table.add_row(escape(p.plan), str(p.proposed), escape(p.reason))
        console.print(table)
    if ambiguous:
        table = Table(title="Ambiguous: a human decides")
        table.add_column("Plan", style="cyan")
        table.add_column("Current")
        table.add_column("Why")
        for p in ambiguous:
            table.add_row(escape(p.plan), escape(p.current or "(none)"), escape(p.reason))
        console.print(table)
    if write:
        console.print(f"Wrote a Status line to {len(written)} plan(s).")
    elif confident:
        console.print("Run again with --apply to write the proposed lines.")
    return 0
