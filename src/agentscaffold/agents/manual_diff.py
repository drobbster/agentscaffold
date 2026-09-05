"""Provenance stamp and three-way section compare for the scaffolded manual."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from agentscaffold.config import ScaffoldConfig
from agentscaffold.rendering import (
    MANAGED_BLOCK_BEGIN,
    get_default_context,
    guidance_hash,
    render_template,
)

MANUAL_STAMP_KEY = "agentscaffold-manual"
_STAMP_RE = re.compile(
    rf"<!--\s*{re.escape(MANUAL_STAMP_KEY)}:\s*(?P<payload>.*?)\s*-->",
    re.DOTALL,
)


@dataclass(frozen=True)
class ManualSection:
    heading: str
    body: str


@dataclass
class ManualStamp:
    sha256: str
    sections: dict[str, str]


@dataclass
class SectionDiff:
    heading: str
    kind: str  # upstream, local, conflict, new_upstream, deleted
    incoming: str | None = None


@dataclass
class ManualDiffReport:
    mode: str  # three_way or two_way
    offered: list[SectionDiff] = field(default_factory=list)
    conflicts: list[SectionDiff] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_h2_sections(text: str) -> list[ManualSection]:
    """Split *text* into `## ` sections, preserving preamble as heading ``""``."""
    lines = text.splitlines()
    sections: list[ManualSection] = []
    current_heading = ""
    current_body: list[str] = []
    for line in lines:
        if line.startswith("## "):
            sections.append(ManualSection(current_heading, "\n".join(current_body).strip("\n")))
            current_heading = line.rstrip()
            current_body = []
        else:
            current_body.append(line)
    sections.append(ManualSection(current_heading, "\n".join(current_body).strip("\n")))
    return [section for section in sections if section.heading or section.body.strip()]


def section_map(text: str) -> dict[str, str]:
    """Map `## ` heading to body. Last write wins if a heading repeats."""
    return {section.heading: section.body for section in parse_h2_sections(text) if section.heading}


def unmanaged_region(text: str) -> str:
    """Return the text before the managed-block markers, or the whole file."""
    begin = text.find(MANAGED_BLOCK_BEGIN)
    if begin == -1:
        return text
    return text[:begin]


def render_governance_manual(config: ScaffoldConfig) -> str:
    """Render the scaffolded governance manual (unstamped)."""
    return render_template("agents/agents_md.md.j2", get_default_context(config))


def build_manual_stamp(unstamped: str) -> ManualStamp:
    """Hash the whole manual and each `## ` section."""
    sections = {
        section.heading: guidance_hash(section.body)
        for section in parse_h2_sections(unstamped)
        if section.heading
    }
    return ManualStamp(sha256=guidance_hash(unstamped), sections=sections)


def render_manual_stamp(stamp: ManualStamp) -> str:
    payload = json.dumps(
        {"sha256": stamp.sha256, "sections": stamp.sections},
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"<!-- {MANUAL_STAMP_KEY}: {payload} -->"


def read_manual_stamp(text: str) -> ManualStamp | None:
    match = _STAMP_RE.search(text)
    if match is None:
        return None
    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return None
    sha = payload.get("sha256")
    sections = payload.get("sections")
    if not isinstance(sha, str) or not isinstance(sections, dict):
        return None
    return ManualStamp(
        sha256=sha, sections={str(key): str(value) for key, value in sections.items()}
    )


def stamp_manual(unstamped: str) -> str:
    """Prefix the provenance comment so a later three-way compare has a base."""
    stamp = render_manual_stamp(build_manual_stamp(unstamped))
    body = unstamped if unstamped.endswith("\n") else unstamped + "\n"
    return f"{stamp}\n\n{body}"


def strip_manual_stamp(text: str) -> str:
    return _STAMP_RE.sub("", text, count=1).lstrip()


def diff_manual(current_text: str, upstream_text: str) -> ManualDiffReport:
    """Compare the project's unmanaged manual against the current template."""
    stamp = read_manual_stamp(current_text)
    local = section_map(strip_manual_stamp(unmanaged_region(current_text)))
    upstream = section_map(upstream_text)
    if stamp is None:
        report = ManualDiffReport(
            mode="two_way",
            notes=[
                "No provenance stamp; comparing current file to the template "
                "without a merge base. Not applying guesses."
            ],
        )
        for heading, body in upstream.items():
            if heading not in local:
                report.offered.append(SectionDiff(heading, "new_upstream", incoming=body))
            elif _norm(local[heading]) != _norm(body):
                report.conflicts.append(SectionDiff(heading, "conflict", incoming=body))
        return report

    report = ManualDiffReport(mode="three_way")
    for heading, body in upstream.items():
        local_body = local.get(heading)
        base_hash = stamp.sections.get(heading)
        upstream_hash = guidance_hash(body)
        if local_body is None:
            if base_hash is None:
                report.offered.append(SectionDiff(heading, "new_upstream", incoming=body))
            # else: project deleted it -- never resurrect
            continue
        local_hash = guidance_hash(local_body)
        local_changed = base_hash is not None and local_hash != base_hash
        upstream_changed = base_hash is None or upstream_hash != base_hash
        if not local_changed and not upstream_changed:
            continue
        if local_changed and not upstream_changed:
            continue
        if not local_changed and upstream_changed:
            report.offered.append(SectionDiff(heading, "upstream", incoming=body))
            continue
        if _norm(local_body) == _norm(body):
            continue
        report.conflicts.append(SectionDiff(heading, "conflict", incoming=body))
    return report


def apply_manual_diff(current_text: str, report: ManualDiffReport) -> str:
    """Apply unambiguous offers. Refuses when *report* has conflicts."""
    if report.conflicts:
        raise ManualDiffConflictError(
            "diff-manual --apply refuses conflicts; resolve them by hand."
        )
    if report.mode == "two_way":
        raise ManualDiffConflictError("diff-manual --apply needs a provenance stamp.")

    unmanaged = unmanaged_region(current_text)
    managed_tail = current_text[len(unmanaged) :]
    body = strip_manual_stamp(unmanaged)
    sections = parse_h2_sections(body)
    by_heading = {section.heading: section for section in sections if section.heading}
    preamble = next((section.body for section in sections if not section.heading), "")
    order = [section.heading for section in sections if section.heading]

    for offer in report.offered:
        if offer.incoming is None:
            continue
        by_heading[offer.heading] = ManualSection(offer.heading, offer.incoming)
        if offer.heading not in order:
            order.append(offer.heading)

    unstamped = _render_sections(preamble, [by_heading[heading] for heading in order])
    stamped = stamp_manual(unstamped)
    if not managed_tail.strip():
        return stamped
    return stamped.rstrip() + "\n\n" + managed_tail.lstrip("\n")


def _render_sections(preamble: str, sections: list[ManualSection]) -> str:
    parts: list[str] = []
    if preamble.strip():
        parts.append(preamble.strip() + "\n")
    for section in sections:
        if not section.heading:
            continue
        body = section.body
        parts.append(f"{section.heading}\n")
        if body:
            parts.append(f"\n{body}\n")
        else:
            parts.append("\n")
    return "\n".join(parts) if parts else ""


def _norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


class ManualDiffConflictError(RuntimeError):
    """--apply refused because the compare is not unambiguous."""


def run_diff_manual(
    path: Path,
    config: ScaffoldConfig,
    *,
    apply: bool = False,
) -> ManualDiffReport:
    """Compare *path*'s unmanaged manual to the current template."""
    current = path.read_text() if path.exists() else ""
    upstream = render_governance_manual(config)
    report = diff_manual(current, upstream)
    if apply:
        if not path.exists():
            raise FileNotFoundError(path)
        path.write_text(apply_manual_diff(current, report))
    return report
