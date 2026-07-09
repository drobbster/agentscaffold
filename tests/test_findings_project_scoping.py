"""Tests for project-scoped review findings (multi-project workspaces).

Plan numbers are not unique across projects, so findings must be stamped with
(and filtered by) their owning project, and the deterministic finding ID must
fold the project in to avoid cross-project ID collisions. Single-project
behavior (``project=None``) must be byte-for-byte unchanged.
"""

from __future__ import annotations

import inspect

from agentscaffold.graph import findings


def test_finding_id_unscoped_is_backward_compatible():
    # project=None must reproduce the original (pre-scoping) hash key.
    legacy_key = "finding::1::quant_architect::correctness::join double-counts"
    import hashlib

    expected = "rf::" + hashlib.sha1(legacy_key.encode()).hexdigest()[:12]  # noqa: S324
    assert (
        findings._finding_id(1, "quant_architect", "correctness", "join double-counts") == expected
    )
    assert (
        findings._finding_id(1, "quant_architect", "correctness", "join double-counts", None)
        == expected
    )


def test_finding_id_differs_across_projects_for_same_content():
    a = findings._finding_id(1, "review", "correctness", "same text", project="alpha")
    b = findings._finding_id(1, "review", "correctness", "same text", project="beta")
    assert a != b


def test_finding_id_is_deterministic_within_a_project():
    a1 = findings._finding_id(1, "review", "correctness", "same text", project="alpha")
    a2 = findings._finding_id(1, "review", "correctness", "same text", project="alpha")
    assert a1 == a2


def test_finding_id_scoped_differs_from_unscoped():
    scoped = findings._finding_id(1, "review", "correctness", "x", project="alpha")
    unscoped = findings._finding_id(1, "review", "correctness", "x")
    assert scoped != unscoped


def test_record_finding_accepts_project_kwarg():
    sig = inspect.signature(findings.record_finding)
    assert "project" in sig.parameters
    assert sig.parameters["project"].default is None


def test_record_findings_batch_accepts_project_kwarg():
    sig = inspect.signature(findings.record_findings_batch)
    assert "project" in sig.parameters
    assert sig.parameters["project"].default is None


def test_resolve_finding_accepts_project_kwarg():
    sig = inspect.signature(findings.resolve_finding)
    assert "project" in sig.parameters
    assert sig.parameters["project"].default is None


def test_get_open_findings_accepts_project_kwarg():
    sig = inspect.signature(findings.get_open_findings)
    assert "project" in sig.parameters
    assert sig.parameters["project"].default is None
