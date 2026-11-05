"""Deliver the governance manual with the tool call it governs.

Orient carries a short block (the `##` headings plus the sections named in
``agents.governance.orient``); each lifecycle tool carries the sections mapped
to its step. Both are bounded by a character budget over the serialized block,
and a section that does not fit is named in ``truncated`` instead of dropped
silently. This module also finds a plan's recorded approval for the
implementation gate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agentscaffold.agents.governance_manual import (
    GovernanceManual,
    load_manual,
    normalize_heading,
)

#: Lifecycle tool -> manual step. Composite tools map to the step they open.
STEP_FOR_TOOL: dict[str, str] = {
    "scaffold_begin_plan": "review",
    "scaffold_prepare_review": "review",
    "scaffold_prepare_implementation": "implementation",
    "scaffold_complete_plan": "completion",
    "scaffold_prepare_retro": "completion",
    "scaffold_record_backlog_item": "backlog",
}

TRUNCATED_HINT = "Call scaffold_governance with section=<heading> for each truncated section."

_APPROVED_LINE = re.compile(r"^-\s*Approved:\s*\d{4}-\d{2}-\d{2} by \S+.*$", re.MULTILINE)
_APPROVAL_REQUIRED = re.compile(r"^-\s*Approval Required:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_APPROVALS_HEADING = re.compile(r"^## Approvals\s*$", re.MULTILINE)


def _agents_config(config: Any) -> Any:
    from agentscaffold.config import AgentsConfig

    return getattr(config, "agents", None) or AgentsConfig()


def project_manual(root: Path, config: Any) -> GovernanceManual | None:
    """The manual for the project at *root*, per ``agents.manual_path``."""
    return load_manual(root, _agents_config(config).manual_path)


def _select(
    manual: GovernanceManual,
    names: list[str],
    optional: list[str],
    budget: int,
    block: dict[str, Any],
) -> dict[str, Any]:
    """Fill ``block`` with the sections for *names* in order, within *budget*.

    A section that does not fit is named in ``truncated`` and later, smaller
    sections are still tried. The finished block, including the truncation
    hint, never exceeds *budget*.
    """
    optional_keys = {_last_key(name) for name in optional}
    block.update({"sections": [], "missing": [], "truncated": []})
    seen: set[str] = set()
    for name in names:
        canonical = manual.resolve(name)
        if canonical is None:
            if _last_key(name) not in optional_keys:
                block["missing"].append(name)
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        block["sections"].append({"heading": canonical, "text": manual.section(canonical) or ""})
        if _size(block) > budget:
            block["sections"].pop()
            block["truncated"].append(canonical)
    if block["truncated"]:
        block["hint"] = TRUNCATED_HINT
        while _size(block) > budget and block["sections"]:
            block["truncated"].append(block["sections"].pop()["heading"])
    return block


def _last_key(name: str) -> str:
    return normalize_heading(name.split(" / ")[-1])


def _size(block: dict[str, Any]) -> int:
    return len(json.dumps(block, ensure_ascii=False))


def orient_block(root: Path, config: Any) -> dict[str, Any]:
    """The ``governance`` block for ``scaffold_orient``."""
    agents = _agents_config(config)
    manual = load_manual(root, agents.manual_path)
    if manual is None:
        return {"path": None, "reason": f"no manual at {agents.manual_path}"}
    governance = agents.governance
    block: dict[str, Any] = {
        "path": manual.path,
        "sha256": manual.sha256,
        "headings": manual.top_headings,
    }
    return _select(
        manual, list(governance.orient), governance.optional, governance.orient_budget, block
    )


def step_block(tool_name: str, root: Path, config: Any) -> dict[str, Any] | None:
    """``governance_sections`` for a lifecycle tool, or ``None`` when nothing applies.

    ``None`` when the tool is not a lifecycle step, no manual exists, or the
    step maps no sections.
    """
    step = STEP_FOR_TOOL.get(tool_name)
    if step is None:
        return None
    agents = _agents_config(config)
    governance = agents.governance
    names = list(getattr(governance.steps, step))
    if not names:
        return None
    manual = load_manual(root, agents.manual_path)
    if manual is None:
        return None
    block: dict[str, Any] = {"step": step, "path": manual.path, "sha256": manual.sha256}
    return _select(manual, names, governance.optional, governance.step_budget, block)


def approval_required(plan_text: str) -> bool:
    """True when the plan's metadata says ``Approval Required: Yes``."""
    match = _APPROVAL_REQUIRED.search(plan_text or "")
    return match is not None and match.group(1).strip().lower().startswith("yes")


def approval_record(
    plan_text: str, plan_number: int, workflow_path: Path | str | None
) -> dict[str, Any] | None:
    """Where the plan's approval is recorded, or ``None``.

    Accepts an ``- Approved: YYYY-MM-DD by <name>`` metadata line in the plan,
    or a ``**Plan N -- APPROVED`` entry under ``## Approvals`` in
    ``workflow_state.md``. ``- Approved: Pending`` is not an approval.
    """
    match = _APPROVED_LINE.search(plan_text or "")
    if match:
        return {"recorded": True, "source": "plan", "line": match.group(0).strip()}
    if workflow_path:
        path = Path(workflow_path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        except OSError:
            text = ""
        line = _approval_in_workflow(text, plan_number)
        if line:
            return {"recorded": True, "source": "workflow_state", "line": line}
    return None


def _approval_in_workflow(text: str, plan_number: int) -> str | None:
    heading = _APPROVALS_HEADING.search(text)
    if heading is None:
        return None
    body = text[heading.end() :]
    following = re.search(r"^## ", body, re.MULTILINE)
    if following:
        body = body[: following.start()]
    entry = re.compile(rf"\*\*Plan\s+0*{int(plan_number)}\b.*APPROVED")
    for line in body.splitlines():
        if entry.search(line):
            return line.strip()
    return None


def approval_gate(plan_number: int) -> dict[str, Any]:
    """The refusal returned while an approval-required plan has no recorded approval."""
    return {
        "blocked": True,
        "reason": "approval_missing",
        "ask": f"Do you approve proceeding with Plan {plan_number} implementation?",
        "record": (
            "After an explicit yes, add '- Approved: YYYY-MM-DD by <name>' to the plan "
            "metadata or an entry under ## Approvals in workflow_state.md."
        ),
    }
