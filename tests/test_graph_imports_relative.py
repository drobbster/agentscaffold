"""Relative Python imports must produce IMPORTS edges -- and only correct ones.

`from .module import name` produced no edge at all: the module string kept its
leading empty part, the candidate path came out with a doubled separator
(`src/pkg//core.py`), `Path.is_file()` normalised that and returned True, so the
resolver reported success and handed back a string `file_id_map` could never
match. The import was then filed unresolved. Measured across this project's own
virtualenv, 22.8% of `from` statements are relative and 75 of 88 packages use
them, while AgentScaffold's own source contains none -- which is why indexing
itself constantly never revealed it.

**The half of this that is not about restoring edges.** The obvious fix is to
drop the empty parts and carry on through the existing resolution strategies,
and that trades missing edges for wrong ones. `from .core import x` reduced to
`core` reaches the absolute-module strategies and matches a top-level `core.py`
belonging to nobody; `from ..core import x` reduces to the identical `core` and
so resolves against the source directory instead of its parent. For a tool whose
question is "what else does this affect?", a confidently wrong edge is worse than
an absent one. The cases below therefore spend as much effort on imports that
must **not** resolve as on ones that must, and several would pass against the
naive fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.graph.imports import _python_module_to_path


@pytest.fixture()
def package_tree(tmp_path: Path) -> Path:
    """A package deep enough for parent-relative imports to mean something.

        src/pkg/__init__.py
        src/pkg/core.py
        src/pkg/rel.py
        src/pkg/sibling.py
        src/pkg/a/b.py
        src/pkg/subpkg/__init__.py
        src/pkg/sub/mod.py
        src/pkg/sub/core.py      <- same name as src/pkg/core.py, one level down
        core.py                  <- same name again, at the repo root

    The two extra ``core.py`` files are the point. They make "resolved to
    something called core" and "resolved to the *right* core" different
    assertions, which a single-core fixture cannot distinguish.
    """
    for rel in (
        "src/pkg/__init__.py",
        "src/pkg/core.py",
        "src/pkg/rel.py",
        "src/pkg/sibling.py",
        "src/pkg/a/__init__.py",
        "src/pkg/a/b.py",
        "src/pkg/subpkg/__init__.py",
        "src/pkg/sub/__init__.py",
        "src/pkg/sub/mod.py",
        "src/pkg/sub/core.py",
        "core.py",
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def f():\n    return 1\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Imports that must resolve
# ---------------------------------------------------------------------------


def test_single_dot_resolves_within_the_same_package(package_tree: Path):
    """`from .core import f` in src/pkg/rel.py means src/pkg/core.py."""
    assert _python_module_to_path(".core", "src/pkg/rel.py", package_tree) == "src/pkg/core.py"


def test_double_dot_ascends_one_package(package_tree: Path):
    """`from ..core import f` in src/pkg/sub/mod.py means src/pkg/core.py.

    Not src/pkg/sub/core.py, which exists and is what dropping the dots would
    select.
    """
    assert _python_module_to_path("..core", "src/pkg/sub/mod.py", package_tree) == "src/pkg/core.py"


def test_bare_dot_imports_a_sibling_module(package_tree: Path):
    """`from . import sibling` -- the module string is a single dot."""
    assert (
        _python_module_to_path(".sibling", "src/pkg/rel.py", package_tree) == "src/pkg/sibling.py"
    )


def test_dotted_relative_path_resolves(package_tree: Path):
    """`from .a.b import c`."""
    assert _python_module_to_path(".a.b", "src/pkg/rel.py", package_tree) == "src/pkg/a/b.py"


def test_relative_import_of_a_package_resolves_to_its_init(package_tree: Path):
    """`from .subpkg import x` where subpkg is a package, not a module."""
    assert (
        _python_module_to_path(".subpkg", "src/pkg/rel.py", package_tree)
        == "src/pkg/subpkg/__init__.py"
    )


# ---------------------------------------------------------------------------
# Imports that must NOT resolve -- the false-edge guards
# ---------------------------------------------------------------------------


def test_a_relative_import_never_falls_through_to_the_repo_root(package_tree: Path):
    """The Strategy 1 fall-through guard.

    `from .missing import x` inside src/pkg must not find a top-level
    missing.py. Here the root holds core.py, so asking for a module that does
    not exist beside the importer while a same-named file sits at the root is
    the exact shape that produces a plausible, wrong edge.
    """
    (package_tree / "missing.py").write_text("def f():\n    return 1\n")

    assert _python_module_to_path(".missing", "src/pkg/rel.py", package_tree) is None


def test_a_relative_import_does_not_match_a_same_named_file_at_the_root(
    package_tree: Path,
):
    """`from .core import f` in a package with no core.py of its own.

    A root-level core.py exists throughout this fixture. Resolving to it would
    assert a dependency between two files that have nothing to do with each
    other.
    """
    result = _python_module_to_path(".core", "src/pkg/subpkg/__init__.py", package_tree)

    assert result != "core.py"
    assert result is None


def test_parent_relative_does_not_settle_for_the_sibling(package_tree: Path):
    """`from ..core import f` must not resolve to src/pkg/sub/core.py.

    Both files exist, so this distinguishes counting the dots from discarding
    them. The naive fix passes every other case in this file and fails here.
    """
    result = _python_module_to_path("..core", "src/pkg/sub/mod.py", package_tree)

    assert result != "src/pkg/sub/core.py"
    assert result == "src/pkg/core.py"


def test_ascending_past_the_root_does_not_resolve(package_tree: Path):
    """`from ....x import y` from a shallow file has nowhere to go."""
    assert _python_module_to_path("....core", "src/pkg/rel.py", package_tree) is None


def test_a_relative_import_of_a_nonexistent_module_stays_unresolved(package_tree: Path):
    assert _python_module_to_path(".nosuchthing", "src/pkg/rel.py", package_tree) is None


# ---------------------------------------------------------------------------
# Absolute imports must be untouched
# ---------------------------------------------------------------------------


def test_absolute_import_still_resolves(package_tree: Path):
    assert _python_module_to_path("pkg.core", "src/pkg/rel.py", package_tree) is not None


def test_absolute_root_module_still_resolves(package_tree: Path):
    assert _python_module_to_path("core", "src/pkg/rel.py", package_tree) == "core.py"


def test_no_returned_path_contains_a_doubled_separator(package_tree: Path):
    """The specific malformation that made this bug silent.

    is_file() normalises `src/pkg//core.py` and returns True, so the resolver
    believed it had succeeded and returned a string no file_id_map key could
    equal. Any future strategy that reintroduces this fails here rather than
    silently dropping edges again.
    """
    modules = (".core", "..core", ".a.b", ".subpkg", "pkg.core", "core")
    sources = ("src/pkg/rel.py", "src/pkg/sub/mod.py")

    for module in modules:
        for source in sources:
            result = _python_module_to_path(module, source, package_tree)
            if result is not None:
                assert "//" not in result, f"{module!r} from {source!r} -> {result!r}"


# ---------------------------------------------------------------------------
# End to end: the edge, not the string
# ---------------------------------------------------------------------------


def test_a_relative_import_produces_an_edge_end_to_end(tmp_path: Path):
    """The assertion that actually matters.

    A unit test on the resolver would have passed at every point in this bug's
    life if the doubled-separator string had happened to normalise on lookup.
    The defect lived only in the gap between the resolver's return value and
    `file_id_map`, so the edge itself is the only honest oracle.
    """
    from agentscaffold.config import load_config
    from agentscaffold.graph.pipeline import run_pipeline

    repo = tmp_path / "repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "src" / "pkg" / "__init__.py").write_text("")
    (repo / "src" / "pkg" / "core.py").write_text("def core_fn():\n    return 1\n")
    (repo / "src" / "pkg" / "rel.py").write_text(
        "from .core import core_fn\n\n\ndef use():\n    return core_fn()\n"
    )
    (repo / "src" / "pkg" / "abs.py").write_text(
        "from pkg.core import core_fn\n\n\ndef use():\n    return core_fn()\n"
    )
    (repo / "scaffold.yaml").write_text("project:\n  name: relrig\n")

    run_pipeline(root=repo, config=load_config(repo / "scaffold.yaml"))

    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    store = DuckPGQBackend(repo / ".scaffold" / "graph.duckdb")
    try:
        rows = store.query("SELECT src, dst FROM IMPORTS")
        edges = {(r["src"], r["dst"]) for r in rows}
    finally:
        store.close()

    relative_edge = ("file::src/pkg/rel.py", "file::src/pkg/core.py")
    absolute_edge = ("file::src/pkg/abs.py", "file::src/pkg/core.py")

    assert absolute_edge in edges, "the absolute import regressed"
    assert relative_edge in edges, (
        "the relative import produced no IMPORTS edge; rel.py appears to depend "
        "on nothing, so scaffold_impact under-reports blast radius"
    )
