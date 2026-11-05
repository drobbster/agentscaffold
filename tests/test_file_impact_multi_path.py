"""File Impact Map cells that list several paths are read as several files.

A cell such as `` `a.py`, `b.py` `` used to be dropped (the row regex allowed
one code span), and an unquoted ``a.py, b.py`` was read as one path.
"""

from __future__ import annotations

import pytest

from agentscaffold.graph.governance import _extract_file_impact


def _rows(*cells: str) -> str:
    body = "\n".join(f"| {cell} | Modify | note |" for cell in cells)
    return (
        "## 6. File Impact Map\n| File | Change Type | Notes |\n|---|---|---|\n"
        f"{body}\n\n## 7. Tests\n"
    )


def _paths(*cells: str) -> list[str]:
    return [i["path"] for i in _extract_file_impact(_rows(*cells))]


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("`src/a.py`, `src/b.py`", ["src/a.py", "src/b.py"]),
        ("`pyproject.toml`, `uv.lock`", ["pyproject.toml", "uv.lock"]),
        ("`docs/x.md` / `docs/y.md`", ["docs/x.md", "docs/y.md"]),
        ("`libs/a.py` + `flows/b.py`", ["libs/a.py", "flows/b.py"]),
        ("`pyproject.toml` or `pytest.ini`", ["pyproject.toml", "pytest.ini"]),
        ("src/a.py, src/b.py", ["src/a.py", "src/b.py"]),
        ("src/a.py and tests/test_a.py", ["src/a.py", "tests/test_a.py"]),
    ],
)
def test_several_paths_in_one_cell(cell: str, expected: list[str]) -> None:
    assert _paths(cell) == expected


def test_bare_file_name_after_a_path_is_in_the_same_folder() -> None:
    cell = (
        "`docs/ai/templates/plan_template.md`, `plan_template_bugfix.md`, "
        "`plan_template_refactor.md`"
    )
    assert _paths(cell) == [
        "docs/ai/templates/plan_template.md",
        "docs/ai/templates/plan_template_bugfix.md",
        "docs/ai/templates/plan_template_refactor.md",
    ]


def test_every_path_keeps_the_row_change_type() -> None:
    impacts = _extract_file_impact(_rows("`src/a.py`, `src/b.py`"))
    assert [i["change_type"] for i in impacts] == ["Modify", "Modify"]


def test_code_names_in_a_cell_are_not_paths() -> None:
    assert _paths("`data_contracts/sec.py` (or the `XBRLFact` home)") == ["data_contracts/sec.py"]
    assert _paths("Fetch helpers (`fetch_bbo` / `_imbalance` / `_trades`)") == []


def test_single_entries_are_unchanged() -> None:
    assert _paths(
        "`Makefile`",
        "justfile",
        "`tests/fixtures/system_inventory/`",
        "`docs/ai/templates/*.md`",
        "`@repo/airflow/dags/nightly.py`",
        "`docs/ai/contracts/x.md` (governance repo)",
        "src/y.py (code repo)",
    ) == [
        "Makefile",
        "justfile",
        "tests/fixtures/system_inventory/",
        "docs/ai/templates/*.md",
        "@repo/airflow/dags/nightly.py",
        "docs/ai/contracts/x.md",
        "src/y.py",
    ]


def test_and_or_inside_a_file_name_do_not_split_it() -> None:
    assert _paths(
        "docs/ai/plans/057-rl-adapter-boundary-and-parity-tests.md",
        "`src/error_or_retry.py`",
    ) == ["docs/ai/plans/057-rl-adapter-boundary-and-parity-tests.md", "src/error_or_retry.py"]


@pytest.mark.parametrize(
    "cell",
    ["src/graph/{search,prune}.py", "`src/graph/{search,prune}.py`"],
)
def test_brace_lists_expand(cell: str) -> None:
    assert _paths(cell) == ["src/graph/search.py", "src/graph/prune.py"]


def test_code_names_inside_a_note_are_not_paths() -> None:
    cell = "The 11 last-bar strategies (`gap_and_go`, `vwap/trend`, `opex_week`)"
    assert _paths(cell) == []
    assert _paths("`src/a.py` (calls `foo`, `lib/bar`)") == ["src/a.py"]


def test_label_before_a_path_is_dropped() -> None:
    assert _paths("governance: docs/ai/contracts/README.md") == ["docs/ai/contracts/README.md"]


def test_prose_cell_is_not_a_path() -> None:
    assert _paths("All plan files", "governance plan + workflow_state") == []


def test_duplicate_paths_in_one_cell_are_listed_once() -> None:
    assert _paths("`src/a.py`, `src/a.py`") == ["src/a.py"]


def test_header_and_separator_rows_are_skipped() -> None:
    assert _extract_file_impact(_rows()) == []
