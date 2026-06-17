"""Tests for graph project scoping (Plan 225, Step 4).

Covers ID qualify/unqualify, fail-closed scope resolution (current/targeted/
federated), current-project detection, and the plain-SQL + GRAPH_TABLE predicate
builders. The "un-scoped read probe" here asserts that a current/targeted scope
always yields a non-empty predicate (so a read that routes through the builder
is scoped); read-callsite wiring is exercised in later phases.
"""

from __future__ import annotations

import pytest

from agentscaffold.graph.scoping import (
    Scope,
    ScopingError,
    current_project_name,
    graph_predicate,
    qualify_id,
    resolve_scope,
    sql_predicate,
    unqualify_id,
)


def _make_project(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text("framework:\n  project_name: X\n")
    (root / ".git").mkdir(exist_ok=True)
    return root


def _make_multi_workspace(root, names):
    root.mkdir(parents=True, exist_ok=True)
    lines = ["projects:"]
    for name in names:
        _make_project(root / name)
        lines.append(f"  - name: {name}")
        lines.append(f"    path: {name}")
    (root / "workspace.yaml").write_text("\n".join(lines) + "\n")
    return root


# ---------------------------------------------------------------------------
# qualify / unqualify
# ---------------------------------------------------------------------------


def test_qualify_id():
    assert qualify_id("alpha", "plan::224") == "alpha::plan::224"


def test_unqualify_splits_on_first_delimiter():
    assert unqualify_id("alpha::plan::224") == ("alpha", "plan::224")


def test_unqualify_unprefixed_without_known_projects_is_best_effort():
    # Without known_projects, a raw id is split best-effort (documented caveat).
    assert unqualify_id("plan::224") == ("plan", "224")


def test_unqualify_with_known_projects_disambiguates():
    known = {"alpha", "beta"}
    assert unqualify_id("plan::224", known) == ("", "plan::224")
    assert unqualify_id("alpha::plan::224", known) == ("alpha", "plan::224")


def test_unqualify_no_delimiter():
    assert unqualify_id("session::uuid-1".replace("::", "_")) == ("", "session_uuid-1")


# ---------------------------------------------------------------------------
# Scope dataclass
# ---------------------------------------------------------------------------


def test_scope_single_project_is_noop():
    s = Scope(project=None, multi=False)
    assert s.is_noop is True
    assert s.is_federated is False


def test_scope_federated():
    s = Scope(project=None, multi=True)
    assert s.is_federated is True
    assert s.is_noop is True


def test_scope_targeted():
    s = Scope(project="alpha", multi=True)
    assert s.is_federated is False
    assert s.is_noop is False


# ---------------------------------------------------------------------------
# resolve_scope (fail-closed)
# ---------------------------------------------------------------------------


def test_resolve_scope_single_project(tmp_path):
    proj = _make_project(tmp_path / "solo")
    s = resolve_scope(start=proj)
    assert s == Scope(project=None, multi=False)


def test_resolve_scope_current_in_multi(tmp_path):
    ws = _make_multi_workspace(tmp_path / "ws", ["alpha", "beta"])
    s = resolve_scope(start=ws / "alpha")
    assert s.multi is True
    assert s.project == "alpha"


def test_resolve_scope_targeted(tmp_path):
    ws = _make_multi_workspace(tmp_path / "ws", ["alpha", "beta"])
    s = resolve_scope(project="beta", start=ws / "alpha")
    assert s.project == "beta"


def test_resolve_scope_federated(tmp_path):
    ws = _make_multi_workspace(tmp_path / "ws", ["alpha", "beta"])
    s = resolve_scope(all_projects=True, start=ws / "alpha")
    assert s.is_federated is True


def test_resolve_scope_unknown_project_raises(tmp_path):
    ws = _make_multi_workspace(tmp_path / "ws", ["alpha", "beta"])
    with pytest.raises(ScopingError, match="Unknown project"):
        resolve_scope(project="gamma", start=ws / "alpha")


# ---------------------------------------------------------------------------
# current_project_name
# ---------------------------------------------------------------------------


def test_current_project_single(tmp_path):
    proj = _make_project(tmp_path / "solo")
    assert current_project_name(proj) == "solo"


def test_current_project_multi_matches_by_path(tmp_path):
    ws = _make_multi_workspace(tmp_path / "ws", ["alpha", "beta"])
    assert current_project_name(ws / "beta") == "beta"


def test_current_project_outside_any_project_raises(tmp_path):
    ws = _make_multi_workspace(tmp_path / "ws", ["alpha", "beta"])
    with pytest.raises(ScopingError):
        current_project_name(ws)


# ---------------------------------------------------------------------------
# Predicate builders (the un-scoped-read probe)
# ---------------------------------------------------------------------------


def test_sql_predicate_noop_for_single_and_federated():
    assert sql_predicate(Scope(None, False)) == ("", [])
    assert sql_predicate(Scope(None, True)) == ("", [])


def test_sql_predicate_scoped():
    frag, params = sql_predicate(Scope("alpha", True))
    assert frag == "project = ?"
    assert params == ["alpha"]


def test_sql_predicate_custom_column():
    frag, params = sql_predicate(Scope("alpha", True), column="e.project")
    assert frag == "e.project = ?"


def test_graph_predicate_scoped_uses_alias():
    frag, params = graph_predicate(Scope("alpha", True), alias="n")
    assert frag == "n.project = ?"
    assert params == ["alpha"]


def test_graph_predicate_noop():
    assert graph_predicate(Scope(None, False), alias="n") == ("", [])


def test_probe_targeted_scope_always_emits_predicate():
    """A current/targeted scope must never produce an empty predicate."""
    for scope in (Scope("alpha", True), Scope("beta", True)):
        frag, params = sql_predicate(scope)
        assert frag and params, "targeted scope must be enforced"
