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

    def artifacts(self, name: str) -> dict[str, str]:
        """The governance identifiers belonging to *name*, and to it alone.

        A conformance test asserts that a tool asked from this project returns
        these and never the other project's, which is the whole point of keeping
        the two sets disjoint.
        """
        return _artifact_ids(self.role(name))

    def other(self, name: str) -> str:
        """The registered name of the project that is *not* *name*."""
        return self.beta_name if name == self.alpha_name else self.alpha_name

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
    # Relative, the form real packages use. It was absolute here only while
    # Plan 252 was open: a leading-dot module resolved to a doubled-separator
    # path that never matched the file map, so this import produced no IMPORTS
    # edge and impact reported no importers. Restoring it keeps the fixture
    # honest about how packages are actually written.
    return f'''"""Imports the shared module, so impact has an edge to report."""

from .shared_module import shared_entry


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
    """Seed governance content that is *attributable* to one project.

    Every artifact here is numbered or named so that seeing it in a response
    proves which project answered: plan 101 means alpha, plan 202 means beta,
    and so on across ADRs, spikes, studies, learnings, contracts and backlog.

    The original fixture carried one plan per project, which was enough to prove
    a governance read is scoped but not enough to exercise the twenty-odd
    governance tools individually -- a tool that reads ADRs cannot be caught
    answering from the wrong project in a workspace with no ADRs, because an
    empty answer discriminates nothing (L249-16). Each artifact type below
    exists so a specific group of tools has something project-specific to be
    right or wrong about.

    Two plans per project, not one, so ``scaffold_compare_plans`` has a pair to
    compare within a single project.
    """
    ids = _artifact_ids(name)

    plans = project / "docs" / "ai" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    for number, suffix in ((ids["plan"], "feature"), (ids["plan_b"], "followup")):
        (plans / f"{number}-{name}-{suffix}.md").write_text(_plan_source(number, name, suffix, ids))

    adrs = project / "docs" / "ai" / "adrs"
    adrs.mkdir(parents=True, exist_ok=True)
    # The topic goes in the *title*: scaffold_find_adrs matches a topic against
    # the ADR title alone, so a title without it makes the tool unable to find
    # its own project's ADR and unable to discriminate anything.
    (adrs / f"{ids['adr']}-{name}-decision.md").write_text(
        f"""# ADR-{ids["adr"]}: {name} {ids["topic"]} storage decision

## Status

Accepted

## Date

2026-01-02

## Context

A decision recorded only in {name}, about {ids["topic"]}.

## Decision

Use the {name} approach for {ids["topic"]}.

## Consequences

Only {name} is affected.
"""
    )

    spikes = project / "docs" / "ai" / "spikes"
    spikes.mkdir(parents=True, exist_ok=True)
    (spikes / f"SPIKE-2026-01-03-{name}-probe.md").write_text(
        f"""# Spike: {name} {ids["topic"]} probe

## Metadata

- Status: Complete
- Related Plan: {ids["plan"]}
- Time Box: 2 hours

## Question

Does the {name} approach to {ids["topic"]} hold up?

## Findings

It does, in {name}.
"""
    )

    studies = project / "docs" / "studies"
    studies.mkdir(parents=True, exist_ok=True)
    (studies / f"STU-2026-01-04-{name}-experiment.md").write_text(
        f"""---
study_id: {ids["study"]}
title: {name} {ids["topic"]} experiment
study_type: ab_test
status: complete
outcome: positive
confidence: high
tags: [{ids["topic"]}]
related_plans: [{ids["plan"]}]
started: 2026-01-04
completed: 2026-01-05
---

# {name} experiment

An experiment run only in {name}.
"""
    )

    contracts = project / "docs" / "ai" / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    (contracts / f"{name}_module_interface.md").write_text(
        f"""# {name} module interface

Version: 1.0

## Exports

- `{ids["topic"]}` -- provided only by {name}.
"""
    )

    state = project / "docs" / "ai" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "workflow_state.md").write_text(
        f"""# Workflow State

## Current Focus

The {name} project, working on plan {ids["plan"]}.

## Blockers

{ids["blocker"]}
"""
    )
    # The table form, not the prose form the governance repo happens to use --
    # the parser recognises tables and a "### L042-1" list, and prose silently
    # yields zero learnings. Built separately because the row has to stay on one
    # physical line for the parser and does not fit the line limit inline.
    learning_row = (
        f"| {ids['learning']} | {ids['plan']} | A lesson about {ids['topic']}, "
        f"recorded only in {name} | AGENTS.md | Pending |"
    )
    (state / "learnings_tracker.md").write_text(
        f"""# Learnings Tracker

## Pending

| ID | Plan | Description | Target | Status |
|----|------|-------------|--------|--------|
{learning_row}

## Incorporated
"""
    )

    (project / "docs" / "ai" / "backlog.md").write_text(
        f"""# Backlog

Last Updated: 2026-01-06

| ID | Title | Priority | Effort | Status | Source |
|----|-------|----------|--------|--------|--------|
| {ids["backlog"]} | A {name} backlog item about {ids["topic"]} | P2 | Small | Open | fixture |
"""
    )


def _artifact_ids(name: str) -> dict[str, str]:
    """Per-project artifact identifiers, disjoint between the two projects.

    Nothing here may collide across projects: a shared identifier would make a
    cross-project answer look correct, which is the failure these fixtures exist
    to detect.
    """
    if name == ALPHA:
        return {
            "plan": "101",
            "plan_b": "102",
            "adr": "011",
            "study": "STU-2026-01-04-alpha-experiment",
            "learning": "L101-1",
            "backlog": "B-ALPHA-1",
            "topic": "alpha_widgets",
            "blocker": "Waiting on the alpha widget review.",
        }
    return {
        "plan": "202",
        "plan_b": "203",
        "adr": "022",
        "study": "STU-2026-01-04-beta-experiment",
        "learning": "L202-1",
        "backlog": "B-BETA-1",
        "topic": "beta_gadgets",
        "blocker": "Waiting on the beta gadget review.",
    }


def _plan_source(number: str, name: str, suffix: str, ids: dict[str, str]) -> str:
    return f"""# Plan {number}: {name} {suffix}

## Metadata

- Status: Draft
- Owner: fixture
- Created: 2026-01-01
- Last Updated: 2026-01-01

## 1. Objective

A plan that exists only in {name}, about {ids["topic"]}, so a governance read
names the project it came from.

## 2. Non-Goals

Anything belonging to the other project.

## 3. Constraints / Invariants

- Must not break: {ids["topic"]}

## 6. File Impact Map

| File | Change Type | Notes |
|------|-------------|-------|
| `src/{name}_module.py` | Modify | the {name} module |

## 7. Tests

| Test File | Coverage Target | Notes |
|-----------|-----------------|-------|
| `tests/test_{name}.py` | 90% | fixture |

## 8. Execution Steps

- [ ] Step 1: do the {name} thing

## 9. Validation

```bash
pytest -q
```

## 10. Rollback Plan

Revert the commit.
"""


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
