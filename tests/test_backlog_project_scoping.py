"""Tests for project-scoped backlog items (multi-project workspaces).

Plan numbers are not unique across projects, so backlog items must be stamped
with (and filtered by) their owning project, and the deterministic backlog ID
must fold the project in to avoid cross-project ID collisions. Single-project
behavior (``project=None``) must be byte-for-byte unchanged.
"""

from __future__ import annotations

import hashlib
import inspect

from agentscaffold.graph import backlog
from agentscaffold.review import queries


def test_backlog_id_unscoped_is_backward_compatible():
    # project=None must reproduce the original (pre-scoping) hash key.
    legacy_key = "backlog::11::ENG-005: decide feature_cost_pool disposition"
    expected = "bi::" + hashlib.sha1(legacy_key.encode()).hexdigest()[:12]  # noqa: S324
    assert backlog._backlog_id(11, "ENG-005: decide feature_cost_pool disposition") == expected
    assert (
        backlog._backlog_id(11, "ENG-005: decide feature_cost_pool disposition", None) == expected
    )


def test_backlog_id_differs_across_projects_for_same_content():
    a = backlog._backlog_id(11, "same title", project="alpha")
    b = backlog._backlog_id(11, "same title", project="beta")
    assert a != b


def test_backlog_id_is_deterministic_within_a_project():
    a1 = backlog._backlog_id(11, "same title", project="alpha")
    a2 = backlog._backlog_id(11, "same title", project="alpha")
    assert a1 == a2


def test_backlog_id_scoped_differs_from_unscoped():
    scoped = backlog._backlog_id(11, "x", project="alpha")
    unscoped = backlog._backlog_id(11, "x")
    assert scoped != unscoped


def test_record_backlog_item_accepts_project_kwarg():
    sig = inspect.signature(backlog.record_backlog_item)
    assert "project" in sig.parameters
    assert sig.parameters["project"].default is None


def test_record_backlog_items_batch_accepts_project_kwarg():
    sig = inspect.signature(backlog.record_backlog_items_batch)
    assert "project" in sig.parameters
    assert sig.parameters["project"].default is None


def test_resolve_backlog_item_accepts_project_kwarg():
    sig = inspect.signature(backlog.resolve_backlog_item)
    assert "project" in sig.parameters
    assert sig.parameters["project"].default is None


def test_get_open_backlog_items_accepts_project_kwarg():
    sig = inspect.signature(backlog.get_open_backlog_items)
    assert "project" in sig.parameters
    assert sig.parameters["project"].default is None


def test_get_backlog_items_for_plan_accepts_project_kwarg():
    sig = inspect.signature(backlog.get_backlog_items_for_plan)
    assert "project" in sig.parameters
    assert sig.parameters["project"].default is None


def test_query_wrappers_expose_scope_kwargs():
    # The review.queries backlog readers must accept project/all_projects so they
    # auto-scope to the current project like the rest of that module.
    for fn in (queries.get_open_backlog_items, queries.get_backlog_items_for_plan):
        params = inspect.signature(fn).parameters
        assert "project" in params, fn.__name__
        assert "all_projects" in params, fn.__name__
        assert params["project"].default is None
        assert params["all_projects"].default is False
