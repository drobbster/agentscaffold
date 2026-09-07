"""Plan 269: a thin mapped subset is not a layer PASS."""

from __future__ import annotations

from agentscaffold.graph.layers import check_layers
from tests.test_layer_validation import FakeStore, _layers, _member


def test_sparse_mapping_is_not_evaluable() -> None:
    members = [_member(f"file::m{i}.py", 1 if i < 4 else 2) for i in range(7)]
    checked = [{"src": "file::m6.py", "dst": "file::m0.py"} for _ in range(14)]
    unmapped = [{"src": "file::m0.py", "dst": f"file::u{i}.py"} for i in range(140)]

    report = check_layers(
        FakeStore(
            layers=_layers(1, 2),
            memberships=members,
            imports=checked + unmapped,
        )
    )

    assert report.status == "not_evaluable"
    assert report.evaluable is False
    assert report.checked_import_count == 14
    assert report.unmapped_import_count == 140
    assert "too thin" in report.reason.lower()


def test_well_mapped_adjacent_import_still_passes() -> None:
    report = check_layers(
        FakeStore(
            layers=_layers(1, 2),
            memberships=[_member("file::a.py", 2), _member("file::b.py", 1)],
            imports=[{"src": "file::a.py", "dst": "file::b.py"}],
        )
    )
    assert report.status == "pass"
    assert report.evaluable is True
