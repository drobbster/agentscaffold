"""De-duplicate already-copied AGENTS.md sections (Plan 260 Scope E)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentscaffold.agents.manual_diff import ManualSection, parse_h2_sections
from agentscaffold.rendering import MANAGED_BLOCK_BEGIN, MANAGED_BLOCK_END, markdown_h2_headings


class ManualRepairConflictError(RuntimeError):
    """Two copies of a section differ; repair will not pick a winner."""


@dataclass
class RepairReport:
    dropped: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.dropped and not self.conflicts


def split_managed(text: str) -> tuple[str, str, str]:
    """Return (prefix, managed_inner_including_markers, suffix)."""
    begin = text.find(MANAGED_BLOCK_BEGIN)
    end = text.find(MANAGED_BLOCK_END)
    if begin == -1 or end == -1 or end <= begin:
        return text, "", ""
    end_full = end + len(MANAGED_BLOCK_END)
    return text[:begin], text[begin:end_full], text[end_full:]


def heading_overlap(text: str) -> list[str]:
    """Headings that appear more than once anywhere in *text*."""
    seen: set[str] = set()
    dupes: list[str] = []
    for heading in markdown_h2_headings(text):
        if heading in seen and heading not in dupes:
            dupes.append(heading)
        seen.add(heading)
    return dupes


def _managed_body(managed: str) -> str:
    """Strip markers and the ownership note so section bodies can be compared."""
    if not managed:
        return ""
    body = managed
    if body.startswith(MANAGED_BLOCK_BEGIN):
        body = body[len(MANAGED_BLOCK_BEGIN) :]
    if MANAGED_BLOCK_END in body:
        body = body[: body.find(MANAGED_BLOCK_END)]
    if "-->" in body:
        body = body[body.find("-->") + 3 :]
    return body


def plan_repair(text: str) -> tuple[str, RepairReport]:
    """Drop exact duplicate `## ` sections. Refuse when copies differ."""
    report = RepairReport()
    prefix, managed, suffix = split_managed(text)
    new_prefix, prefix_report = _dedupe_region(prefix)
    report.dropped.extend(prefix_report.dropped)
    report.conflicts.extend(prefix_report.conflicts)

    if managed:
        managed_sections = {
            section.heading: section.body
            for section in parse_h2_sections(_managed_body(managed))
            if section.heading
        }
        prefix_sections = {
            section.heading: section.body
            for section in parse_h2_sections(new_prefix)
            if section.heading
        }
        for heading, body in managed_sections.items():
            if heading not in prefix_sections:
                continue
            if _norm(body) == _norm(prefix_sections[heading]):
                report.dropped.append(heading)
            else:
                report.conflicts.append(heading)
        if report.conflicts:
            raise ManualRepairConflictError(
                "repair refuses to guess where copies differ: " + ", ".join(report.conflicts)
            )
        if report.dropped:
            # Rebuild the managed region without headings that matched the prefix.
            drop = {heading for heading in report.dropped if heading in prefix_sections}
            kept = [
                section
                for section in parse_h2_sections(_managed_body(managed))
                if not section.heading or section.heading not in drop
            ]
            from agentscaffold.rendering import render_managed_block

            rebuilt = _join_sections(kept).strip()
            managed = render_managed_block(rebuilt) if rebuilt else ""
            if managed and not managed.endswith("\n"):
                managed += "\n"

    combined = new_prefix.rstrip() + ("\n\n" + managed if managed else "") + suffix
    if heading_overlap(new_prefix):
        new_prefix, again = _dedupe_region(new_prefix)
        report.dropped.extend(again.dropped)
        report.conflicts.extend(again.conflicts)
        combined = new_prefix.rstrip() + ("\n\n" + managed if managed else "") + suffix

    if report.conflicts:
        raise ManualRepairConflictError(
            "repair refuses to guess where copies differ: " + ", ".join(report.conflicts)
        )
    if not report.dropped:
        report.notes.append("No duplicate headings.")
    if not combined.endswith("\n"):
        combined += "\n"
    return combined, report


def _dedupe_region(text: str) -> tuple[str, RepairReport]:
    report = RepairReport()
    sections = parse_h2_sections(text)
    kept: list[ManualSection] = []
    first_body: dict[str, str] = {}
    for section in sections:
        if not section.heading:
            kept.append(section)
            continue
        if section.heading not in first_body:
            first_body[section.heading] = _norm(section.body)
            kept.append(section)
            continue
        if _norm(section.body) == first_body[section.heading]:
            report.dropped.append(section.heading)
            continue
        report.conflicts.append(section.heading)
        kept.append(section)
    return _join_sections(kept), report


def _join_sections(sections: list[ManualSection]) -> str:
    parts: list[str] = []
    for section in sections:
        if section.heading:
            parts.append(section.heading)
            if section.body:
                parts.append(section.body)
            parts.append("")
        elif section.body:
            parts.append(section.body.rstrip())
            parts.append("")
    rendered = "\n".join(parts)
    return rendered if rendered.endswith("\n") else rendered + "\n"


def _norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def run_repair(path: Path, *, apply: bool = False) -> RepairReport:
    """De-duplicate *path*. Dry run by default; ``--apply`` writes."""
    text = path.read_text()
    updated, report = plan_repair(text)
    if apply and updated != text:
        path.write_text(updated)
    return report
