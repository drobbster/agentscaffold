"""``scaffold_inventory``: check, review packet, and one component with provenance."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest

from agentscaffold.config import ScaffoldConfig, load_config
from agentscaffold.mcp.inventory_tool import ENABLE_HINT, SUMMARY_CAP, inventory_tool

FIXTURES = Path(__file__).parent / "fixtures" / "system_inventory"
TODAY = dt.date(2026, 11, 5)


@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, ScaffoldConfig]:
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "project", root)
    return root, load_config(root / "scaffold.yaml")


def _call(project: tuple[Path, ScaffoldConfig], **arguments: object) -> dict:
    root, config = project
    return inventory_tool(arguments, root, config, today=TODAY)


def test_disabled_inventory_says_how_to_enable(tmp_path: Path) -> None:
    result = inventory_tool({}, tmp_path, ScaffoldConfig())
    assert result == {"enabled": False, "hint": ENABLE_HINT}
    assert "scaffold inventory enable" in ENABLE_HINT


def test_check_is_the_contract_json(project: tuple[Path, ScaffoldConfig]) -> None:
    result = _call(project)
    assert result["view"] == "check"
    assert result["mode"] == "warn"
    assert result["schema_version"] == 1
    assert result["summary"]["components"] == 12
    assert any(f["id"] == "INV-011" for f in result["findings"])


def test_review_is_the_packet(project: tuple[Path, ScaffoldConfig]) -> None:
    result = _call(project, mode="review")
    assert result["view"] == "review"
    assert [u["component"] for u in result["unresolved"]] == ["compose:sidecar"]
    assert result["has_debt"] is True


def test_component_shows_effective_values_with_provenance(
    project: tuple[Path, ScaffoldConfig],
) -> None:
    derived = _call(project, mode="component", component_id="compose:cache")
    assert derived["found"] is True
    assert derived["component"] == "compose:cache"
    assert derived["image"] == "fixture/cache:7"
    assert derived["fields"]["owner_plan"] == {
        "value": "150",
        "from": "file_impact_map_create",
    }
    assert derived["fields"]["layer"]["from"] == "owner_plan"

    pinned = _call(project, mode="component", component_id="compose:api")
    assert pinned["fields"]["owner_plan"] == {"value": "150", "from": "pin"}

    unresolved = _call(project, mode="component", component_id="compose:sidecar")
    assert unresolved["fields"]["owner_plan"] == {"value": None, "from": None}
    assert [f["id"] for f in unresolved["findings"]] == ["INV-011"]


def test_unknown_component_suggests_close_ids(project: tuple[Path, ScaffoldConfig]) -> None:
    result = _call(project, mode="component", component_id="compose:cach")
    assert result["found"] is False
    assert "compose:cache" in result["suggestions"]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"mode": "delete"}, "mode must be one of check, review, component"),
        ({"mode": "component"}, "mode 'component' needs component_id"),
    ],
)
def test_bad_arguments_are_errors(
    project: tuple[Path, ScaffoldConfig], arguments: dict, message: str
) -> None:
    assert message in _call(project, **arguments)["error"]


def test_unreadable_inventory_is_an_error_with_remediation(
    project: tuple[Path, ScaffoldConfig],
) -> None:
    root, _ = project
    (root / "docs/ai/system_inventory.yaml").write_text("components: [unclosed\n")
    result = _call(project, mode="component", component_id="compose:api")
    assert result["error"]
    assert "scaffold inventory check" in result["remediation"]


def test_the_server_dispatches_and_stamps_meta(project: tuple[Path, ScaffoldConfig]) -> None:
    from agentscaffold.mcp.server import _tool_inventory

    root, config = project
    result = _tool_inventory(None, {"mode": "check"}, {"stamp": 1}, root, config)
    assert result["meta"] == {"stamp": 1}
    assert result["view"] == "check"


def test_the_tool_is_advertised_read_only() -> None:
    from agentscaffold.mcp.registry import WRITE_TOOLS, tool_specs

    spec = next(s for s in tool_specs() if s.name == "scaffold_inventory")
    assert spec.input_schema["properties"]["mode"]["enum"] == ["check", "review", "component"]
    assert "working_path" in spec.input_schema["properties"]
    assert "scaffold_inventory" not in WRITE_TOOLS


def test_review_carries_markdown_and_caps_lists_in_summary(
    project: tuple[Path, ScaffoldConfig],
) -> None:
    summary = _call(project, mode="review")
    assert summary["markdown"].startswith("# System inventory review, 2026-11-05")
    for key in ("duplicates", "unreferenced", "unresolved"):
        assert len(summary[key]) <= SUMMARY_CAP
    full = _call(project, mode="review", detail="full")
    assert "counts" not in full
    assert summary["counts"]["unreferenced"] == len(full["unreferenced"])


def test_component_governance_comes_from_the_entrypoint_file(
    project: tuple[Path, ScaffoldConfig],
) -> None:
    root, config = project
    asked: list[str] = []

    def lookup(target: str) -> dict:
        asked.append(target)
        return {"adrs": [{"id": "ADR-001"}]}

    result = inventory_tool(
        {"mode": "component", "component_id": "prefect:nightly-ingest"},
        root,
        config,
        today=TODAY,
        governance=lookup,
    )
    assert asked == ["flows/ingest.py"]
    assert result["governance"] == {"adrs": [{"id": "ADR-001"}]}

    image_only = inventory_tool(
        {"mode": "component", "component_id": "compose:sidecar"},
        root,
        config,
        today=TODAY,
        governance=lookup,
    )
    assert "governance" not in image_only
