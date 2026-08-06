"""A two-project workspace fixture for conformance and smoke tests.

Phase F has to answer "did this tool resolve to the *right* project?" for every
registered tool. That question is only answerable against a workspace where the
projects are distinguishable, so this builds one deliberately:

* ``alpha_only`` / ``beta_only`` exist in exactly one project. Finding one proves
  which project answered.
* ``shared_name`` exists in **both**, with different bodies and different
  callers. This is the case that matters. A tool that resolves to the wrong
  project still returns a plausible result for a name both projects define, so a
  test that only ever asks about unique symbols would pass against broken
  routing. Asking about ``shared_name`` and checking *which* body came back is
  what actually discriminates.
* Each project has a **second module importing the first**, because a tool can
  only be caught answering from the wrong project if it has something to say.
  With one file per project, ``scaffold_impact`` returned empty importer and
  caller lists for both, which is indistinguishable from correct scoping and
  from a broken tool. An empty answer discriminates nothing.

The workspace is built once and indexed once, because indexing is the expensive
part; registration into the per-test registry is cheap and happens per test.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ALPHA = "alpha"
BETA = "beta"

#: Defined only in alpha, only in beta, and in both (with differing bodies).
ALPHA_ONLY_SYMBOL = "alpha_only_widget"
BETA_ONLY_SYMBOL = "beta_only_gadget"
SHARED_SYMBOL = "shared_name"

#: Module name present in both projects with identical *relative* path, so a
#: path-keyed lookup that ignores the project resolves ambiguously. The importer
#: of it differs per project, which is what makes impact attributable.
SHARED_MODULE_RELPATH = "src/shared_module.py"


@dataclass(frozen=True)
class TwoProjectWorkspace:
    """Paths and known content of the built workspace."""

    root: Path
    alpha: Path
    beta: Path
    db_path: Path
    #: Registered project names. Configurable because names must be unique
    #: across the whole registry, so a second workspace registered alongside the
    #: shared one cannot reuse them.
    alpha_name: str = ALPHA
    beta_name: str = BETA

    @property
    def names(self) -> tuple[str, str]:
        return (self.alpha_name, self.beta_name)

    def project_root(self, name: str) -> Path:
        return {self.alpha_name: self.alpha, self.beta_name: self.beta}[name]

    def source_file(self, name: str) -> Path:
        """A real file inside *name*, suitable for passing as ``working_path``."""
        return self.project_root(name) / "src" / f"{self.role(name)}_module.py"

    def role(self, name: str) -> str:
        """The fixture role (``alpha``/``beta``) behind a registered project name."""
        return ALPHA if name == self.alpha_name else BETA

    def expected_importer(self, name: str) -> str:
        """The only file importing ``shared_module`` inside *name*.

        Asking impact about :data:`SHARED_MODULE_RELPATH` -- which exists at the
        same path in both projects -- must come back with this project's
        consumer and no other.
        """
        return f"src/{self.role(name)}_consumer.py"


_ALPHA_SOURCE = f'''"""Alpha's only module."""


def {ALPHA_ONLY_SYMBOL}(value):
    """Exists only in alpha."""
    return value * 2


def {SHARED_SYMBOL}(value):
    """Defined in both projects. Alpha's body doubles."""
    return {ALPHA_ONLY_SYMBOL}(value)


def alpha_caller(value):
    return {SHARED_SYMBOL}(value)
'''

#: Lives at the *same relative path* in both projects, so a lookup keyed on path
#: alone cannot tell them apart -- the case that catches a tool resolving by
#: path without a project. Its importer is named per project, which is what
#: makes the answer attributable.
_SHARED_MODULE_SOURCE = '''"""Present in both projects at an identical path."""


def shared_entry(value):
    return value
'''


def _consumer_source(role: str) -> str:
    # Absolute, not ``from .shared_module import`` -- the resolver turns a
    # leading-dot module into a path with a doubled separator
    # (``src//shared_module.py``), which never matches the file map, so a
    # relative import produces no IMPORTS edge at all. Tracked separately; using
    # the absolute form here keeps this fixture measuring project scoping rather
    # than import resolution.
    return f'''"""Imports the shared module, so impact has an edge to report."""

from shared_module import shared_entry


def {role}_consume(value):
    return shared_entry(value)
'''


_BETA_SOURCE = f'''"""Beta's only module."""


def {BETA_ONLY_SYMBOL}(value):
    """Exists only in beta."""
    return value + 100


def {SHARED_SYMBOL}(value):
    """Defined in both projects. Beta's body adds."""
    return {BETA_ONLY_SYMBOL}(value)
'''


def build_two_project_workspace(
    root: Path, *, alpha_name: str = ALPHA, beta_name: str = BETA
) -> TwoProjectWorkspace:
    """Create (but do not index) a two-project workspace under *root*."""
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "graph.duckdb"

    (root / "workspace.yaml").write_text(
        "projects:\n"
        f"  - name: {alpha_name}\n    path: {ALPHA}\n"
        f"  - name: {beta_name}\n    path: {BETA}\n"
    )

    for role, name, source in (
        (ALPHA, alpha_name, _ALPHA_SOURCE),
        (BETA, beta_name, _BETA_SOURCE),
    ):
        project = root / role
        (project / "src").mkdir(parents=True, exist_ok=True)
        (project / "src" / f"{role}_module.py").write_text(source)
        (project / "src" / "shared_module.py").write_text(_SHARED_MODULE_SOURCE)
        (project / "src" / f"{role}_consumer.py").write_text(_consumer_source(role))
        # The graph path is pinned explicitly so the fixture does not depend on
        # which state directory the workspace id happens to resolve to -- that
        # varies with AGENTSCAFFOLD_HOME, which is isolated per test.
        (project / "scaffold.yaml").write_text(
            f"project:\n  name: {name}\ngraph:\n  db_path: {db_path}\n"
        )
        _write_governance(project, role)

    return TwoProjectWorkspace(
        root=root,
        alpha=root / ALPHA,
        beta=root / BETA,
        db_path=db_path,
        alpha_name=alpha_name,
        beta_name=beta_name,
    )


def _write_governance(project: Path, name: str) -> None:
    """Seed the minimum governance a discovery tool can return something from.

    Each project gets exactly one plan, numbered differently, so a governance
    read is as attributable as a code read: plan 101 means alpha answered.
    """
    plans = project / "docs" / "ai" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    number = "101" if name == ALPHA else "202"
    (plans / f"{number}-{name}-plan.md").write_text(
        f"""# Plan {number}: {name} feature

## Metadata

- Status: Draft
- Owner: fixture
- Created: 2026-01-01

## 1. Objective

A plan that exists only in {name}, so a governance read names the project it
came from.

## Execution Steps

- [ ] Step 1: do the {name} thing
"""
    )

    state = project / "docs" / "ai" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "workflow_state.md").write_text(
        f"# Workflow State\n\n## Current Focus\n\nThe {name} project.\n\n## Blockers\n\nNone.\n"
    )


def index_workspace(workspace: TwoProjectWorkspace) -> None:
    """Build the shared graph, with each project's rows namespaced to it."""
    from agentscaffold.config import load_config
    from agentscaffold.graph.pipeline import run_pipeline

    for project in (workspace.alpha, workspace.beta):
        run_pipeline(root=project, config=load_config(project / "scaffold.yaml"))


#: Registry roots in each path flavour, for tests that must cover Windows and
#: WSL shapes on a POSIX host. These are recorded strings, not real directories:
#: the package repo has no Windows runner, and the logic under test parses the
#: recorded string rather than asking the host. See ``test_cross_platform_paths``.
PATH_FLAVOUR_VARIANTS = {
    "windows": (
        (ALPHA, r"C:\workspace\alpha"),
        (BETA, r"C:\workspace\beta"),
    ),
    "windows_unc": (
        (ALPHA, r"\\server\share\workspace\alpha"),
        (BETA, r"\\server\share\workspace\beta"),
    ),
    "wsl": (
        (ALPHA, "/mnt/c/workspace/alpha"),
        (BETA, "/mnt/c/workspace/beta"),
    ),
    "posix": (
        (ALPHA, "/home/dev/workspace/alpha"),
        (BETA, "/home/dev/workspace/beta"),
    ),
}
