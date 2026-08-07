"""Tests for ``scaffold_projects`` and opt-in federated discovery (Plan 249, A7).

Two behaviours are under test and they are related.

``scaffold_projects`` is the escape hatch from the refusals A6b introduced. Once
the server can answer "I will not guess which project you mean", it owes the
agent a way to find out what the valid answers are -- including when the current
call is itself unresolvable, which is exactly when it is needed most.

Federated discovery is the other half: cross-project reads are opt-in per call,
and a federated result must never be mistakable for a local one. For row-shaped
results that means per-row ``project`` provenance. For ``scaffold_decision_context``
it means something stronger -- plan numbers repeat across projects, so federating
a plan number is a question with several answers, and the tool refuses rather
than returning whichever row the database happened to order first.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")


@pytest.fixture(autouse=True)
def restore_cwd():
    """Dispatch chdirs into the resolved project; put it back (see A6b)."""
    original = os.getcwd()
    try:
        yield
    finally:
        os.chdir(original)


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "home"
    target.mkdir()
    monkeypatch.setenv("AGENTSCAFFOLD_HOME", str(target))
    return target


def _project(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text(f"project:\n  name: {name}\n")
    return root


# ---------------------------------------------------------------------------
# scaffold_projects
# ---------------------------------------------------------------------------


def test_lists_registered_projects_with_roots(home: Path, tmp_path: Path) -> None:
    from agentscaffold.mcp.projects import build_projects_payload
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(_project(tmp_path / "alpha", "alpha"), name="alpha")
    register_workspace(_project(tmp_path / "beta", "beta"), name="beta")

    payload = build_projects_payload(None)

    assert [p["name"] for p in payload["projects"]] == ["alpha", "beta"]
    assert payload["count"] == 2
    assert all(p["registered"] for p in payload["projects"])
    assert payload["projects"][0]["project_root"].endswith("alpha")
    assert payload["projects"][0]["workspace_id"]


def test_reports_which_project_the_call_resolved_to_and_why(home: Path, tmp_path: Path) -> None:
    """Source is the point: an anchored answer and a routed answer differ."""
    from agentscaffold.mcp.project_resolution import resolve_project
    from agentscaffold.mcp.projects import build_projects_payload
    from agentscaffold.workspace_registry import register_workspace

    alpha = _project(tmp_path / "alpha", "alpha")
    register_workspace(alpha, name="alpha")
    register_workspace(_project(tmp_path / "beta", "beta"), name="beta")

    payload = build_projects_payload(resolve_project(project="beta", anchor=alpha))

    assert payload["active_project"]["name"] == "beta"
    assert payload["active_project"]["source"] == "explicit"


def test_active_project_is_listed_even_when_unregistered(home: Path, tmp_path: Path) -> None:
    """A lone repo resolves fine but was never registered; still list it.

    Reporting an active project that is absent from the project list would make
    the tool contradict itself in the single-repo case, which is the common one.
    """
    from agentscaffold.mcp.project_resolution import resolve_project
    from agentscaffold.mcp.projects import build_projects_payload

    solo = _project(tmp_path / "solo", "solo")

    payload = build_projects_payload(resolve_project(anchor=solo))

    names = [p["name"] for p in payload["projects"]]
    assert names == ["solo"]
    assert payload["projects"][0]["registered"] is False
    assert payload["active_project"]["name"] == "solo"


def test_empty_registry_explains_itself(home: Path) -> None:
    from agentscaffold.mcp.projects import build_projects_payload

    payload = build_projects_payload(None)

    assert payload["projects"] == []
    assert "register" in payload["why_empty"]


def test_restrict_to_is_reported_per_project(home: Path, tmp_path: Path) -> None:
    """An allowlisted server should say what it will and will not answer for."""
    from agentscaffold.mcp.projects import build_projects_payload
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(_project(tmp_path / "alpha", "alpha"), name="alpha")
    register_workspace(_project(tmp_path / "beta", "beta"), name="beta")

    payload = build_projects_payload(None, restrict_to={"alpha"})

    allowed = {p["name"]: p["allowed"] for p in payload["projects"]}
    assert allowed == {"alpha": True, "beta": False}
    assert payload["restricted_to"] == ["alpha"]


def test_no_allowed_flag_when_no_allowlist_is_active(home: Path, tmp_path: Path) -> None:
    """A bare False on every row would read as denied rather than not-applicable."""
    from agentscaffold.mcp.projects import build_projects_payload
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(_project(tmp_path / "alpha", "alpha"), name="alpha")

    payload = build_projects_payload(None)

    assert "allowed" not in payload["projects"][0]
    assert "restricted_to" not in payload


def test_dispatch_answers_projects_even_when_resolution_fails(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recovery path: ambiguous everywhere else, still answerable here."""
    import agentscaffold.mcp.server as server_mod
    from agentscaffold.mcp.server import _dispatch_tool
    from agentscaffold.workspace_registry import register_workspace

    register_workspace(_project(tmp_path / "alpha", "alpha"), name="alpha")
    register_workspace(_project(tmp_path / "beta", "beta"), name="beta")

    bare = tmp_path / "not-a-project"
    bare.mkdir()
    monkeypatch.setattr(server_mod, "_effective_mcp_root", lambda *a, **k: bare)

    # Every other tool refuses under these conditions (see A6b tests).
    assert _dispatch_tool("scaffold_orient", {})["error_code"] == "ambiguous_project"

    result = _dispatch_tool("scaffold_projects", {})

    assert [p["name"] for p in result["projects"]] == ["alpha", "beta"]
    assert result["unresolved"]["error_code"] == "ambiguous_project"


def test_projects_tool_is_advertised() -> None:
    from agentscaffold.mcp.server import _get_tool_definitions

    tools = {t.name for t in _get_tool_definitions()}
    assert "scaffold_projects" in tools


# ---------------------------------------------------------------------------
# Federated discovery
# ---------------------------------------------------------------------------


def test_discovery_tools_advertise_opt_in_federation() -> None:
    """Cross-project reads must be requestable, and only on request."""
    from agentscaffold.mcp.server import _get_tool_definitions

    by_name = {t.name: t for t in _get_tool_definitions()}
    for name in (
        "scaffold_find_studies",
        "scaffold_find_adrs",
        "scaffold_decision_context",
    ):
        props = by_name[name].inputSchema["properties"]
        assert "all_projects" in props, name
        assert props["all_projects"]["default"] is False, name
        assert "project" in props, name


def test_federated_study_query_selects_project_provenance() -> None:
    """A merged result set is unreadable without knowing each row's origin."""
    from agentscaffold.graph.scoping import Scope
    from agentscaffold.review.queries import _provenance_select

    assert _provenance_select(Scope(project=None, multi=True), "s") == (', project AS "s.project"')


def test_scoped_and_single_project_reads_omit_provenance() -> None:
    """A NULL project on every row of a lone repo reads as missing data."""
    from agentscaffold.graph.scoping import Scope
    from agentscaffold.review.queries import _provenance_select

    assert _provenance_select(Scope(project="alpha", multi=True), "s") == ""
    assert _provenance_select(Scope(project=None, multi=False), "s") == ""


def test_find_studies_echoes_a_federated_scope() -> None:
    """A federated answer must not be mistakable for a local one."""
    from agentscaffold.mcp.server import _tool_find_studies

    class _Store:
        def query(self, *a, **k):
            return []

    captured: dict = {}

    import agentscaffold.review.queries as q

    def _tags(store, tags, *, project=None, all_projects=False):
        captured["scope"] = (project, all_projects)
        return []

    original = q.get_studies_by_tags
    q.get_studies_by_tags = _tags
    try:
        out = _tool_find_studies(_Store(), {"topic": "x", "all_projects": True}, {})
    finally:
        q.get_studies_by_tags = original

    assert captured["scope"] == (None, True)
    assert out["scope"] == "all_projects"


def test_decision_context_refuses_a_plan_number_owned_by_several_projects() -> None:
    """Plan numbers repeat across projects, so federating one is ambiguous.

    Answering with whichever project sorted first would splice one project's
    ADRs onto another's plan and say nothing about it.
    """
    import agentscaffold.review.queries as q
    from agentscaffold.mcp.server import _tool_decision_context

    original = q.get_plan_projects
    q.get_plan_projects = lambda store, number: ["alpha", "beta"]
    try:
        out = _tool_decision_context(object(), {"plan_number": 249, "all_projects": True}, {})
    finally:
        q.get_plan_projects = original

    assert out["error_code"] == "ambiguous_project"
    assert out["candidates"] == ["alpha", "beta"]


def test_decision_context_answers_when_the_number_is_unique(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One owner is not ambiguous, so federation narrows to it and says so."""
    import agentscaffold.review.queries as q
    from agentscaffold.mcp.server import _tool_decision_context

    monkeypatch.setattr(q, "get_plan_projects", lambda store, number: ["beta"])
    monkeypatch.setattr(
        q,
        "get_plan_by_number",
        lambda store, n, *, project=None, all_projects=False: {
            "p.title": "T",
            "p.status": "Complete",
        },
    )
    for fn in (
        "get_adrs_for_plan",
        "get_spikes_for_plan",
        "get_studies_for_plan",
        "get_plan_dependencies",
    ):
        monkeypatch.setattr(q, fn, lambda store, n, *, project=None, all_projects=False: [])

    class _Store:
        def get_stats(self):
            return {"nodes": 1}

    out = _tool_decision_context(_Store(), {"plan_number": 249, "all_projects": True}, {})

    assert out["project"] == "beta"
    assert "error_code" not in out
