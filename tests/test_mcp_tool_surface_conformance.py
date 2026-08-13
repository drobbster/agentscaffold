"""Phase F conformance: every tool in the live registry, against every guarantee.

Parametrized over :func:`tool_specs` rather than a hardcoded list, so a tool
added later is covered automatically and a tool that skips these guarantees
fails the build instead of quietly not being tested.

**On writing the oracles.** The natural phrasing for a scoping guarantee is
"alpha's answer should differ from beta's", and that phrasing is a trap: a tool
that errors, or returns nothing, satisfies it in neither direction while
appearing to satisfy it in both. Two empty results compare equal, and so do two
error payloads. Every case here therefore asserts *what the answer should be*
per project, not merely that the two differ.

The same care applies to where the answer is read from. Tool payloads carry
``meta``, ``grep_fallback`` and ``coverage`` fields built from the resolved
project root, so a payload-wide substring check attributes correctly no matter
what the underlying query returned. These cases read substantive result rows
only -- see :func:`_rows_only`.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentscaffold.mcp.registry import tool_names, tool_specs

# Fields carrying graph results. Everything else in a payload is derived from
# the resolved root and would attribute to the right project regardless.
_ROW_FIELDS = (
    "node",
    "callers",
    "callees",
    "results",
    "hits",
    "direct_importers",
    "transitive_importers",
    "callers_into_file",
    "method_callers_into_file",
)


def _rows_only(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k in _ROW_FIELDS}


def _dispatch(tool: str, workspace, asked_from: str, **arguments: Any) -> dict[str, Any]:
    """Call *tool* as if the agent were working inside *asked_from*.

    The positional is not named ``project`` so a case can pass ``project=`` as a
    real tool argument without colliding with it.
    """
    from agentscaffold.mcp.server import _dispatch_tool

    arguments["working_path"] = str(workspace.source_file(asked_from))
    return _dispatch_tool(tool, arguments)


# ---------------------------------------------------------------------------
# C4 -- a tool answers from the project its working_path resolves to
# ---------------------------------------------------------------------------


def test_context_answers_from_the_project_the_working_path_resolves_to(two_project_workspace):
    """The C4 case that matters: a symbol both projects define.

    Asking about a name unique to one project would pass against completely
    broken routing, because there is only one row to find. ``shared_name``
    exists in both with different bodies, so the callee names say which project
    answered.
    """
    from tests.fixtures.multiproject import (
        ALPHA_ONLY_SYMBOL,
        BETA_ONLY_SYMBOL,
        SHARED_SYMBOL,
    )

    ws = two_project_workspace
    expected = {ws.alpha_name: ALPHA_ONLY_SYMBOL, ws.beta_name: BETA_ONLY_SYMBOL}

    for project, own_symbol in expected.items():
        payload = _dispatch("scaffold_context", ws, project, symbol=SHARED_SYMBOL)
        callees = [c.get("name") for c in (payload.get("callees") or [])]

        # Positive assertion per project, not "the two differ".
        assert own_symbol in callees, (
            f"asked from {project}, expected its own {own_symbol} among callees, got {callees}"
        )
        foreign = {ALPHA_ONLY_SYMBOL, BETA_ONLY_SYMBOL} - {own_symbol}
        assert not foreign & set(callees), (
            f"asked from {project}, leaked another project's symbol: {callees}"
        )


def test_impact_answers_from_the_project_the_working_path_resolves_to(two_project_workspace):
    """Same guarantee for a path-keyed tool.

    ``shared_module.py`` sits at an identical relative path in both projects, so
    a lookup that keys on path without a project cannot tell them apart. Only
    the importer differs, which is what makes the answer attributable.
    """
    from tests.fixtures.multiproject import SHARED_MODULE_RELPATH

    ws = two_project_workspace
    for project in ws.names:
        payload = _dispatch("scaffold_impact", ws, project, file_or_symbol=SHARED_MODULE_RELPATH)
        importers = {
            row.get("filePath") or row.get("path")
            for row in (payload.get("direct_importers") or [])
        }
        assert ws.expected_importer(project) in importers, (
            f"asked from {project}, expected {ws.expected_importer(project)} "
            f"among importers, got {sorted(importers)}"
        )
        other = ws.beta_name if project == ws.alpha_name else ws.alpha_name
        assert ws.expected_importer(other) not in importers, (
            f"asked from {project}, leaked {other}'s importer: {sorted(importers)}"
        )


def test_search_answers_from_the_project_the_working_path_resolves_to(two_project_workspace):
    from tests.fixtures.multiproject import SHARED_SYMBOL

    ws = two_project_workspace
    for project in ws.names:
        payload = _dispatch("scaffold_search", ws, project, query=SHARED_SYMBOL, mode="keyword")
        paths = " ".join(str(r.get("path", "")) for r in (payload.get("results") or []))
        assert paths.strip(), f"asked from {project}, search returned nothing to attribute"
        assert f"{ws.role(project)}_module" in paths, f"asked from {project}, got paths {paths}"


def test_governance_recall_answers_from_the_resolved_project(two_project_workspace):
    """Alpha owns plan 101 and beta owns 202; neither may see the other's."""
    ws = two_project_workspace
    owned = {ws.alpha_name: ("101", "202"), ws.beta_name: ("202", "101")}

    for project, (mine, theirs) in owned.items():
        payload = _dispatch("scaffold_recall_governance", ws, project, query="feature")
        blob = str(payload.get("results") or payload)
        assert mine in blob, f"asked from {project}, expected plan {mine}: {blob[:200]}"
        assert theirs not in blob, f"asked from {project}, leaked plan {theirs}"


def test_explicit_project_argument_overrides_the_resolved_one(two_project_workspace):
    """Fail-closed scoping is only tolerable with a way to look elsewhere.

    Asking from alpha for beta's symbol must return beta's answer, or the
    not-found in the default scope becomes a dead end.
    """
    from tests.fixtures.multiproject import BETA_ONLY_SYMBOL, SHARED_SYMBOL

    ws = two_project_workspace
    payload = _dispatch(
        "scaffold_context", ws, ws.alpha_name, symbol=SHARED_SYMBOL, project=ws.beta_name
    )
    callees = [c.get("name") for c in (payload.get("callees") or [])]
    assert BETA_ONLY_SYMBOL in callees, f"explicit project=beta not honoured: {callees}"


def test_a_symbol_only_in_a_sibling_project_is_reported_not_found(two_project_workspace):
    """The chosen fail-closed behaviour, asserted rather than assumed.

    Answering from the sibling would be the old bug wearing a different hat: a
    confident answer about a project the caller is not in.
    """
    from tests.fixtures.multiproject import BETA_ONLY_SYMBOL

    ws = two_project_workspace
    payload = _dispatch("scaffold_context", ws, ws.alpha_name, symbol=BETA_ONLY_SYMBOL)
    assert payload.get("error"), (
        f"expected not-found for beta's symbol asked from alpha, got {list(payload)}"
    )


def test_stats_labels_its_totals_as_workspace_wide(two_project_workspace):
    """Stats counts the whole workspace; the payload has to say so.

    The number itself is not the bug -- reporting it next to ``working_path``
    without saying what it covers is, because every neighbouring tool answers
    about one project and the reader has no way to tell this one does not.
    """
    ws = two_project_workspace
    payload = _dispatch("scaffold_stats", ws, ws.alpha_name)
    scope = payload.get("scope") or {}

    assert scope.get("kind") == "workspace", f"stats did not label its scope: {scope}"
    assert set(ws.names) <= set(scope.get("projects") or []), (
        f"scope names the wrong projects: {scope}"
    )
    assert scope.get("current_project") == ws.alpha_name


# ---------------------------------------------------------------------------
# C2 -- every tool accepts working_path and none rejects it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", tool_specs(), ids=lambda s: s.name)
def test_every_tool_advertises_working_path(spec):
    assert "working_path" in spec.input_schema.get("properties", {}), (
        f"{spec.name} does not accept working_path, so it cannot be project-scoped"
    )


@pytest.mark.parametrize("spec", tool_specs(), ids=lambda s: s.name)
def test_every_declared_argument_describes_itself(spec):
    """A property key with stray whitespace is silently not a description.

    Nothing else fails when it happens: the schema stays valid JSON, lint sees a
    well-formed dict literal, and the tool keeps working. The only casualty is
    the guidance the agent needed to call the tool correctly.
    """
    for prop_name, prop in spec.input_schema.get("properties", {}).items():
        assert all(key == key.strip() for key in prop), (
            f"{spec.name}.{prop_name} has a whitespace-padded schema key: {list(prop)}"
        )
        assert prop.get("description", "").strip(), (
            f"{spec.name}.{prop_name} has no description for the agent to read"
        )


@pytest.mark.parametrize(
    "name",
    [n for n in tool_names() if n in {"scaffold_context", "scaffold_impact", "scaffold_search"}],
)
def test_code_tools_can_be_retargeted_and_federated(name):
    """Scoping fail-closed is only defensible with a way to widen the search.

    A symbol that exists only in a sibling project reports as not-found under
    the default scope, so the tools have to offer an explicit way to ask
    elsewhere -- which the governance tools already had and these did not.
    """
    from agentscaffold.mcp.registry import get_tool_spec

    properties = get_tool_spec(name).input_schema.get("properties", {})
    assert "project" in properties, f"{name} cannot be retargeted at a sibling project"
    assert "all_projects" in properties, f"{name} cannot federate across the workspace"


# ---------------------------------------------------------------------------
# Waivers -- recorded, with reasons, so a gap is visible rather than absent
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="C1 (intent map) is completed by Plan 251, Phase E")
def test_c1_intent_map_is_derived_from_the_registry():
    raise AssertionError("declared but not implemented here")


@pytest.mark.skip(reason="C3 (scope stamp) is completed by Plan 251, Phase E")
def test_c3_every_response_carries_a_scope_stamp():
    raise AssertionError("declared but not implemented here")


@pytest.mark.skip(
    reason=(
        "scaffold_query takes raw user SQL; injecting a project predicate into an "
        "arbitrary statement is not tractable. Waived by decision, documented as "
        "workspace-wide."
    )
)
def test_query_is_project_scoped():
    raise AssertionError("waived by decision, not by omission")
