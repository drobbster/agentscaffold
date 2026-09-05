"""Tests for the two-project fixture itself.

A fixture that cannot tell the two projects apart would let the whole Phase F
conformance suite pass against broken routing. These tests establish that it
discriminates, so the suites built on it are measuring what they claim to.
"""

from __future__ import annotations

import pytest

from tests.fixtures.multiproject import (
    ALPHA,
    ALPHA_ONLY_SYMBOL,
    BETA,
    BETA_ONLY_SYMBOL,
    PATH_FLAVOUR_VARIANTS,
    SHARED_SYMBOL,
    TwoProjectWorkspace,
    build_two_project_workspace,
)


def test_the_workspace_has_two_registered_projects(two_project_workspace: TwoProjectWorkspace):
    from agentscaffold.workspace_registry import load_registry

    registry = load_registry()
    assert sorted(registry.project_names()) == [ALPHA, BETA]


def test_each_project_has_a_symbol_the_other_does_not(
    two_project_workspace: TwoProjectWorkspace,
):
    alpha_src = two_project_workspace.source_file(ALPHA).read_text()
    beta_src = two_project_workspace.source_file(BETA).read_text()

    assert ALPHA_ONLY_SYMBOL in alpha_src and ALPHA_ONLY_SYMBOL not in beta_src
    assert BETA_ONLY_SYMBOL in beta_src and BETA_ONLY_SYMBOL not in alpha_src


def test_both_projects_define_the_shared_symbol_differently(
    two_project_workspace: TwoProjectWorkspace,
):
    """The discriminating case.

    If the two definitions were identical, a tool answering from the wrong
    project would return the right-looking thing and the conformance suite would
    call that a pass.
    """
    alpha_src = two_project_workspace.source_file(ALPHA).read_text()
    beta_src = two_project_workspace.source_file(BETA).read_text()

    assert f"def {SHARED_SYMBOL}(" in alpha_src
    assert f"def {SHARED_SYMBOL}(" in beta_src
    assert ALPHA_ONLY_SYMBOL in alpha_src.split(f"def {SHARED_SYMBOL}(")[1]
    assert BETA_ONLY_SYMBOL in beta_src.split(f"def {SHARED_SYMBOL}(")[1]


def test_the_graph_namespaces_each_project_separately(
    two_project_workspace: TwoProjectWorkspace,
):
    """One graph, two projects, and a query can tell which rows belong to which.

    This is the property every scoped read depends on. If both projects wrote
    into one undifferentiated namespace, scoping would have nothing to scope by.
    """
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    store = DuckPGQBackend(two_project_workspace.db_path)
    try:
        rows = store.query(
            "SELECT project, name FROM Function WHERE name IN (?, ?, ?)",
            {"a": ALPHA_ONLY_SYMBOL, "b": BETA_ONLY_SYMBOL, "c": SHARED_SYMBOL},
        )
    finally:
        store.close()

    by_symbol: dict[str, set[str]] = {}
    for row in rows:
        by_symbol.setdefault(row["name"], set()).add(row["project"])

    assert by_symbol[ALPHA_ONLY_SYMBOL] == {ALPHA}
    assert by_symbol[BETA_ONLY_SYMBOL] == {BETA}
    assert by_symbol[SHARED_SYMBOL] == {ALPHA, BETA}, (
        "the shared symbol must exist in both namespaces, or it cannot "
        "discriminate between a correct and an incorrect resolution"
    )


def test_each_project_owns_a_distinctly_numbered_plan(
    two_project_workspace: TwoProjectWorkspace,
):
    """Governance reads need to be attributable the same way code reads are."""
    alpha_plans = sorted(
        p.name for p in (two_project_workspace.alpha / "docs/ai/plans").glob("*.md")
    )
    beta_plans = sorted(p.name for p in (two_project_workspace.beta / "docs/ai/plans").glob("*.md"))

    assert alpha_plans == ["101-alpha-feature.md", "102-alpha-followup.md"]
    assert beta_plans == ["202-beta-feature.md", "203-beta-followup.md"]


def test_no_governance_identifier_is_shared_between_the_projects(
    two_project_workspace: TwoProjectWorkspace,
):
    """The property the whole C4 extension rests on.

    If any identifier appeared in both projects, a tool answering from the wrong
    one would return something the test recognises as correct. The fixture would
    then certify scoping it never checked.
    """
    alpha = two_project_workspace.artifacts(two_project_workspace.alpha_name)
    beta = two_project_workspace.artifacts(two_project_workspace.beta_name)

    shared = {k for k in alpha if alpha[k] == beta[k]}
    assert not shared, f"identifiers collide across projects: {shared}"


def test_working_path_points_at_a_real_file_in_each_project(
    two_project_workspace: TwoProjectWorkspace,
):
    for name in (ALPHA, BETA):
        path = two_project_workspace.source_file(name)
        assert path.is_file()
        assert path.is_relative_to(two_project_workspace.project_root(name))


def test_the_scratch_workspace_is_not_the_shared_one(
    two_project_workspace: TwoProjectWorkspace,
    scratch_two_project_workspace: TwoProjectWorkspace,
):
    """A write test must not be able to disturb what read tests share.

    Holding both at once also proves the two can coexist in one registry, which
    they only can because their project names differ -- names are unique across
    the whole registry, not per workspace.
    """
    assert scratch_two_project_workspace.root != two_project_workspace.root
    assert scratch_two_project_workspace.db_path != two_project_workspace.db_path
    assert set(scratch_two_project_workspace.names).isdisjoint(two_project_workspace.names)


def test_rebuilding_the_workspace_is_deterministic(tmp_path):
    first = build_two_project_workspace(tmp_path / "one")
    second = build_two_project_workspace(tmp_path / "two")

    assert first.source_file(ALPHA).read_text() == second.source_file(ALPHA).read_text()
    assert (first.root / "workspace.yaml").read_text() == (
        second.root / "workspace.yaml"
    ).read_text()


# ---------------------------------------------------------------------------
# Path-flavour variant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flavour", sorted(PATH_FLAVOUR_VARIANTS))
def test_each_path_flavour_variant_resolves_its_own_projects(flavour):
    """Windows, UNC, WSL and POSIX roots each resolve correctly from a POSIX host.

    The package repo has no Windows runner, so the variant is recorded strings
    rather than real directories -- which is the honest thing to test, since the
    resolution logic parses the recorded path rather than asking the host.
    """
    from agentscaffold.path_flavour import path_contains

    variants = PATH_FLAVOUR_VARIANTS[flavour]
    separator = "\\" if flavour.startswith("windows") else "/"

    for name, root in variants:
        child = f"{root}{separator}src{separator}{name}_module.py"
        assert path_contains(root, child), f"{flavour}: {root} should contain {child}"

    (alpha_name, alpha_root), (beta_name, beta_root) = variants
    beta_child = f"{beta_root}{separator}src{separator}{beta_name}_module.py"
    assert not path_contains(alpha_root, beta_child), (
        f"{flavour}: sibling projects must not capture each other's paths"
    )


def test_windows_and_wsl_roots_do_not_cross_match():
    """The same directory reached two ways stays two registrations.

    Deliberate: how ``/mnt`` is mounted cannot be known from here, so treating
    them as one would resolve calls to the wrong project whenever the guess was
    wrong.
    """
    from agentscaffold.path_flavour import path_contains

    windows_root = PATH_FLAVOUR_VARIANTS["windows"][0][1]
    wsl_child = PATH_FLAVOUR_VARIANTS["wsl"][0][1] + "/src/alpha_module.py"

    assert not path_contains(windows_root, wsl_child)
