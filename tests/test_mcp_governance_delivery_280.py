"""Plan 280: the governance manual delivered with orient and the lifecycle tools."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentscaffold.agents.governance_manual import parse_manual
from agentscaffold.agents.manual_diff import render_governance_manual
from agentscaffold.config import AgentsConfig, GovernanceConfig, ScaffoldConfig
from agentscaffold.mcp.governance_delivery import (
    STEP_FOR_TOOL,
    TRUNCATED_HINT,
    orient_block,
    step_block,
)

FIXTURE = Path(__file__).parent / "fixtures" / "governance" / "agents_md_governance_repo.md"


def _size(block: dict) -> int:
    return len(json.dumps(block, ensure_ascii=False))


def _project_with(tmp_path: Path, manual: str, **governance) -> tuple[Path, SimpleNamespace]:
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    (root / "AGENTS.md").write_text(manual, encoding="utf-8")
    config = SimpleNamespace(agents=AgentsConfig(governance=GovernanceConfig(**governance)))
    return root, config


# --- unit level ----------------------------------------------------------------


def test_default_mapping_fits_the_shipped_template() -> None:
    config = ScaffoldConfig()
    manual = parse_manual(render_governance_manual(config))
    governance = config.agents.governance
    mapped = list(governance.orient)
    for step in ("review", "implementation", "completion", "backlog"):
        mapped += getattr(governance.steps, step)
    assert [name for name in mapped if manual.resolve(name) is None] == []


def test_orient_block_for_this_repositorys_manual(tmp_path) -> None:
    root, config = _project_with(tmp_path, FIXTURE.read_text(encoding="utf-8"))
    block = orient_block(root, config)
    assert block["path"] == "AGENTS.md"
    assert len(block["sha256"]) == 64
    assert block["headings"][0] == "Repository Relationship"
    assert all(" / " not in heading for heading in block["headings"])
    assert [s["heading"] for s in block["sections"]] == ["Hard Prohibitions", "Approval Gates"]
    assert block["missing"] == [] and block["truncated"] == []
    assert _size(block) <= 2800


def test_a_section_that_does_not_fit_is_named_not_dropped(tmp_path) -> None:
    root, config = _project_with(tmp_path, FIXTURE.read_text(encoding="utf-8"), orient_budget=1800)
    block = orient_block(root, config)
    assert [s["heading"] for s in block["sections"]] == ["Hard Prohibitions"]
    assert block["truncated"] == ["Approval Gates"]
    assert block["hint"] == TRUNCATED_HINT
    assert _size(block) <= 1800


def test_a_smaller_later_section_still_fits(tmp_path) -> None:
    manual = "## Big\n" + "x" * 900 + "\n\n## Small\nshort\n"
    root, config = _project_with(tmp_path, manual, orient=["Big", "Small"], orient_budget=400)
    block = orient_block(root, config)
    assert [s["heading"] for s in block["sections"]] == ["Small"]
    assert block["truncated"] == ["Big"]


def test_missing_and_optional_headings(tmp_path) -> None:
    manual = "## Execution Rules\nrun\n\n## Component Lifecycle\nlife\n"
    steps = {"implementation": ["Execution Rules", "Component Lifecycle", "Nonexistent Rules"]}
    root, config = _project_with(tmp_path, manual, steps=steps, optional=["Component Lifecycle"])
    block = step_block("scaffold_prepare_implementation", root, config)
    assert [s["heading"] for s in block["sections"]] == ["Execution Rules", "Component Lifecycle"]
    assert block["missing"] == ["Nonexistent Rules"]

    (root / "AGENTS.md").write_text("## Execution Rules\nrun, edited\n", encoding="utf-8")
    block = step_block("scaffold_prepare_implementation", root, config)
    assert block["missing"] == ["Nonexistent Rules"]
    assert [s["heading"] for s in block["sections"]] == ["Execution Rules"]


def test_a_step_with_no_mapping_carries_nothing(tmp_path) -> None:
    root, config = _project_with(tmp_path, "## Backlog Rules\nb\n", steps={"backlog": []})
    assert step_block("scaffold_record_backlog_item", root, config) is None
    assert step_block("scaffold_search", root, config) is None


def test_no_manual(tmp_path) -> None:
    config = SimpleNamespace(agents=AgentsConfig())
    assert orient_block(tmp_path, config) == {"path": None, "reason": "no manual at AGENTS.md"}
    assert step_block("scaffold_prepare_review", tmp_path, config) is None


def test_delivery_is_deterministic(tmp_path) -> None:
    root, config = _project_with(tmp_path, FIXTURE.read_text(encoding="utf-8"))
    assert orient_block(root, config) == orient_block(root, config)


# --- dispatch level ------------------------------------------------------------

pytest.importorskip("duckdb", reason="duckdb not installed")


@pytest.fixture
def project(tmp_path):
    from tests.fixtures.lone_project import STALE_WORKFLOW, build_lone_project

    return build_lone_project(
        tmp_path,
        workflow=STALE_WORKFLOW,
        draft_plan=True,
        manual=FIXTURE.read_text(encoding="utf-8"),
    )


def _call(name: str, root: Path, **arguments):
    from agentscaffold.mcp.server import _dispatch_tool

    return _dispatch_tool(name, {"working_path": str(root), **arguments})


_STEP_CALLS = {
    "scaffold_begin_plan": {"plan_number": 90, "dry_run": True},
    "scaffold_prepare_review": {"plan_number": 90},
    "scaffold_prepare_implementation": {"plan_number": 90},
    "scaffold_complete_plan": {"plan_number": 90, "dry_run": True},
    "scaffold_prepare_retro": {"plan_number": 90},
    "scaffold_record_backlog_item": {
        "plan_number": 90,
        "items": [{"title": "Measure retries"}],
        "dry_run": True,
    },
}


def test_every_lifecycle_tool_carries_its_step(project) -> None:
    assert set(_STEP_CALLS) == set(STEP_FOR_TOOL)
    for name, arguments in _STEP_CALLS.items():
        result = _call(name, project, **arguments)
        assert "error" not in result, (name, result.get("error"))
        block = result["governance_sections"]
        assert block["step"] == STEP_FOR_TOOL[name], name
        assert block["sections"], name
        assert block["missing"] == [], (name, block["missing"])
        assert _size(block) <= 6000, name


def test_composite_tools_carry_one_copy(project) -> None:
    for name in ("scaffold_begin_plan", "scaffold_complete_plan"):
        result = _call(name, project, **_STEP_CALLS[name])
        text = json.dumps(result)
        assert text.count('"governance_sections"') == 1, name


def test_orient_carries_the_block(project) -> None:
    result = _call("scaffold_orient", project)
    block = result["governance"]
    assert block["path"] == "AGENTS.md"
    assert [s["heading"] for s in block["sections"]] == ["Hard Prohibitions", "Approval Gates"]


def test_a_heading_missing_from_the_manual_does_not_fail_the_tool(tmp_path) -> None:
    from tests.fixtures.lone_project import build_lone_project

    root = build_lone_project(
        tmp_path,
        draft_plan=True,
        manual="## Backlog Rules (Mandatory)\nkeep it short\n",
        extra_config=(
            "agents:\n  governance:\n    steps:\n"
            "      backlog: [Backlog Rules, Nonexistent Rules]\n"
        ),
    )
    result = _call(
        "scaffold_record_backlog_item", root, **_STEP_CALLS["scaffold_record_backlog_item"]
    )
    assert "error" not in result
    assert result["governance_sections"]["missing"] == ["Nonexistent Rules"]
    assert result["governance_sections"]["sections"][0]["heading"] == "Backlog Rules (Mandatory)"


def test_without_a_manual(tmp_path) -> None:
    from tests.fixtures.lone_project import build_lone_project

    root = build_lone_project(tmp_path, draft_plan=True)
    assert _call("scaffold_orient", root)["governance"] == {
        "path": None,
        "reason": "no manual at AGENTS.md",
    }
    assert "governance_sections" not in _call("scaffold_prepare_review", root, plan_number=90)


def test_error_responses_carry_no_block(project) -> None:
    result = _call("scaffold_prepare_review", project)
    assert "error" in result
    assert "governance_sections" not in result


def test_governance_tool_table_of_contents_and_sections(project) -> None:
    toc = _call("scaffold_governance", project)
    assert "Plan Lifecycle / Gate: Ready -> In Progress" in toc["headings"]
    assert len(toc["sha256"]) == 64

    found = _call("scaffold_governance", project, section="Plan Lifecycle / Ready -> In Progress")
    assert found["found"] is True
    assert found["section"] == "Plan Lifecycle / Gate: Ready -> In Progress"
    assert "Plan review checklist completed" in found["text"]

    missing = _call("scaffold_governance", project, section="Backlog Rulez")
    assert missing["found"] is False
    assert missing["suggestions"][0] == "Backlog Rules (Mandatory)"
    assert len(missing["suggestions"]) == 3


def test_governance_tool_follows_working_path(tmp_path) -> None:
    from tests.fixtures.lone_project import build_lone_project

    first = build_lone_project(tmp_path, name="first", manual="## Alpha\na\n")
    second = build_lone_project(tmp_path, name="second", manual="## Beta\nb\n")
    assert _call("scaffold_governance", first)["headings"] == ["Alpha"]
    assert _call("scaffold_governance", second)["headings"] == ["Beta"]


def test_governance_tool_without_a_manual(tmp_path) -> None:
    from tests.fixtures.lone_project import build_lone_project

    root = build_lone_project(tmp_path)
    result = _call("scaffold_governance", root)
    assert result["path"] is None
    assert result["reason"] == "no manual at AGENTS.md"
