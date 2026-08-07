"""Tests for the ``layers`` architecture check behind ``scaffold_validate``.

The check enforces the rule stated in `AGENTS.md`: a component consumes its
upstream layer and does not bypass intermediate ones. Two shapes violate it --
an import that runs *upward* (a lower layer depending on a higher one, which
inverts the architecture) and one that *skips* (reaching past an intermediate
layer).

The hardest requirement here is not detecting violations. It is refusing to
report "no violations" when the check cannot see anything, which is the state
this repository is actually in: layer definitions live in the governance repo
and the code lives in the package repo, so in either graph alone one half is
missing. A check that answers "clean" there would be lying in the most
convincing possible way, and most of the tests below exist to pin that down.
"""

from __future__ import annotations

import pytest

from agentscaffold.graph.layers import LayerReport, check_layers


class FakeStore:
    """A graph stub returning canned rows, keyed by the table being queried."""

    def __init__(self, layers=None, memberships=None, imports=None):
        self._layers = layers or []
        self._memberships = memberships or []
        self._imports = imports or []

    def query(self, sql, params=None):
        lowered = sql.lower()
        if "architecturelayer" in lowered and "belongs_to_layer" not in lowered:
            return list(self._layers)
        if "belongs_to_layer" in lowered:
            return list(self._memberships)
        if "imports" in lowered:
            return list(self._imports)
        return []


def _layers(*numbers):
    return [{"id": f"layer::{n}", "number": n, "name": f"Layer {n}"} for n in numbers]


def _member(file_id, layer_number):
    return {"src": file_id, "dst": f"layer::{layer_number}", "number": layer_number}


# ---------------------------------------------------------------------------
# Refusing to answer when it cannot see
# ---------------------------------------------------------------------------


def test_no_layers_defined_is_not_evaluable():
    """No architecture document means nothing to check against."""
    report = check_layers(FakeStore())

    assert report.evaluable is False
    assert report.violations == []
    assert "no architecture layers" in report.reason.lower()


def test_layers_defined_but_no_files_mapped_is_not_evaluable():
    """The exact state of this repository's split between governance and code.

    Layers are defined and no file matches any of their path patterns, so the
    check has definitions on one side and nothing on the other. Reporting zero
    violations from that would be indistinguishable from a clean codebase.
    """
    report = check_layers(FakeStore(layers=_layers(1, 2, 3)))

    assert report.evaluable is False
    assert report.violations == []
    assert "no files" in report.reason.lower()
    assert report.remediation, "a non-evaluable result must say how to make it evaluable"


def test_a_non_evaluable_report_is_not_reported_as_passing():
    """The single most important assertion in this file.

    Everything else is a correctness detail. This is the one that stops the
    check from joining the list of instruments that fail toward good news.
    """
    report = check_layers(FakeStore(layers=_layers(1, 2)))

    assert report.status != "pass"
    assert report.status == "not_evaluable"


# ---------------------------------------------------------------------------
# Detecting the two violation shapes
# ---------------------------------------------------------------------------


def test_an_upward_import_is_a_violation():
    """Layer 2 importing layer 5 inverts the architecture."""
    report = check_layers(
        FakeStore(
            layers=_layers(1, 2, 3, 4, 5),
            memberships=[_member("file::low.py", 2), _member("file::high.py", 5)],
            imports=[{"src": "file::low.py", "dst": "file::high.py"}],
        )
    )

    assert report.evaluable is True
    assert report.status == "fail"
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation["kind"] == "inversion"
    assert violation["from_layer"] == 2
    assert violation["to_layer"] == 5


def test_skipping_an_intermediate_layer_is_a_violation():
    """Layer 5 reaching directly into layer 2 bypasses 3 and 4."""
    report = check_layers(
        FakeStore(
            layers=_layers(1, 2, 3, 4, 5),
            memberships=[_member("file::high.py", 5), _member("file::low.py", 2)],
            imports=[{"src": "file::high.py", "dst": "file::low.py"}],
        )
    )

    assert report.status == "fail"
    assert report.violations[0]["kind"] == "skip"
    assert report.violations[0]["skipped"] == [3, 4]


def test_consuming_the_layer_directly_below_is_allowed():
    """The permitted case, and the one that must not be flagged."""
    report = check_layers(
        FakeStore(
            layers=_layers(1, 2, 3),
            memberships=[_member("file::a.py", 3), _member("file::b.py", 2)],
            imports=[{"src": "file::a.py", "dst": "file::b.py"}],
        )
    )

    assert report.evaluable is True
    assert report.status == "pass"
    assert report.violations == []


def test_imports_within_one_layer_are_allowed():
    report = check_layers(
        FakeStore(
            layers=_layers(1, 2),
            memberships=[_member("file::a.py", 2), _member("file::b.py", 2)],
            imports=[{"src": "file::a.py", "dst": "file::b.py"}],
        )
    )

    assert report.status == "pass"


def test_imports_involving_an_unmapped_file_are_ignored_not_guessed():
    """A file belonging to no layer says nothing about layering.

    Treating it as layer 0, or as a violation, would invent a finding out of
    missing data.
    """
    report = check_layers(
        FakeStore(
            layers=_layers(1, 2, 3),
            memberships=[_member("file::a.py", 3)],
            imports=[{"src": "file::a.py", "dst": "file::unmapped.py"}],
        )
    )

    assert report.status == "pass"
    assert report.violations == []
    assert report.unmapped_import_count == 1, (
        "an ignored import must still be counted, or the report overstates its own coverage"
    )


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------


def test_violations_are_ordered_and_carry_the_files():
    """Stable, actionable output: two runs diff, and each row names the file."""
    report = check_layers(
        FakeStore(
            layers=_layers(1, 2, 3, 4),
            memberships=[
                _member("file::z.py", 4),
                _member("file::a.py", 4),
                _member("file::low.py", 1),
            ],
            imports=[
                {"src": "file::z.py", "dst": "file::low.py"},
                {"src": "file::a.py", "dst": "file::low.py"},
            ],
        )
    )

    assert [v["from_file"] for v in report.violations] == ["file::a.py", "file::z.py"]
    assert all(v["to_file"] == "file::low.py" for v in report.violations)


def test_the_report_survives_a_broken_graph():
    """A query failure is not evaluable; it is certainly not a pass."""

    class Broken:
        def query(self, sql, params=None):
            raise RuntimeError("graph is unavailable")

    report = check_layers(Broken())

    assert report.evaluable is False
    assert report.status == "not_evaluable"
    assert "unavailable" in report.reason.lower()


def test_report_serializes_for_the_mcp_payload():
    report = check_layers(FakeStore(layers=_layers(1)))
    payload = report.to_dict()

    assert payload["status"] == "not_evaluable"
    assert "violations" in payload and "reason" in payload


@pytest.mark.parametrize("status", ["pass", "fail", "not_evaluable"])
def test_status_values_are_closed(status):
    assert status in LayerReport.STATUSES
