"""C4 conformance for the governance-reading tools.

Plan 249 proved project scoping for four tools and left twenty-five untested,
which is the largest gap it closed nothing of: C4 is the guarantee the whole
multi-project effort exists to deliver, and both bugs found at Phase F were in
the four tools that happened to be checked.

**The probe.** For a tool keyed on a plan number, the sharpest possible question
is to ask one project for the *other* project's plan. Alpha owns plans 101 and
102; beta owns 202 and 203. Asking beta for plan 101, from a working path inside
beta, has exactly one correct answer: not found. A tool that returns alpha's plan
has reached across a boundary it was told to respect, and no amount of plausible
content makes that right.

This is a sharper instrument than comparing alpha's answer to beta's. Two
projects that both answer "not found" compare equal, and so do two that both
answer from the same wrong place. Asking for something that must not be there
turns scoping into a question with a knowably correct answer.

**On vacuity.** A tool that errors, or returns nothing, passes any
"must not contain the other project" assertion for free -- the failure mode that
made the Plan 249 smoke tests pass against a silent no-op. Every case here
therefore pairs the negative with a positive: the same tool asked for its *own*
plan must find it. A tool that cannot satisfy the positive is reported as
undiscriminating rather than passing.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fixtures.multiproject import ALPHA, BETA

#: Tools keyed on a single plan number, which is the strongest probe available.
PLAN_KEYED_TOOLS = [
    "scaffold_review_context",
    "scaffold_prepare_review",
    "scaffold_prepare_implementation",
    "scaffold_staleness_check",
    "scaffold_prepare_rewrite",
    "scaffold_prepare_retro",
    "scaffold_decision_context",
    "scaffold_prior_experiments",
    "scaffold_diff_plan_vs_code",
]

#: Tools keyed on a free-text topic or query, with the field their substantive
#: rows arrive in. Reading that field rather than the whole payload is essential:
#: every one of these echoes the query back, and ``why_empty`` repeats it again,
#: so a payload-wide search for the other project's token finds it on a response
#: whose result set is correctly empty. Asserting against the echo reports five
#: correctly-scoped tools as leaking.
TOPIC_KEYED_TOOLS = [
    ("scaffold_find_studies", "topic", "studies"),
    ("scaffold_find_adrs", "topic", "adrs"),
    ("scaffold_recall_governance", "query", "results"),
    ("scaffold_grep_graph", "pattern", "hits"),
]

#: The plan each project owns, and the topic token that appears only in its
#: governance content. The token never occurs in a filesystem path, so finding
#: it in a response body is evidence about content rather than about the
#: resolved root.
OWNED = {
    ALPHA: {"plan": 101, "token": "alpha_widgets", "foreign_plan": 202},
    BETA: {"plan": 202, "token": "beta_gadgets", "foreign_plan": 101},
}


def _call(tool: str, workspace, asked_from: str, **arguments: Any) -> dict[str, Any]:
    from agentscaffold.mcp.server import _dispatch_tool

    arguments["working_path"] = str(workspace.source_file(asked_from))
    return _dispatch_tool(tool, arguments)


def _body(payload: dict[str, Any]) -> str:
    """The response minus ``meta``, as text.

    ``meta`` is built from the resolved root and would attribute correctly no
    matter what the query returned, so including it would make every assertion
    below pass for the wrong reason.
    """
    return json.dumps({k: v for k, v in payload.items() if k != "meta"}, default=str)


def _rows(payload: dict[str, Any], field: str) -> str:
    """Just the substantive result rows, as text.

    Every tool here echoes its own query argument back, and ``why_empty``
    repeats it a second time, so reading the whole payload finds the other
    project's token on a response whose results are correctly empty.
    """
    return json.dumps(payload.get(field, []), default=str)


def _says_plan_missing(payload: dict[str, Any], plan: int) -> bool:
    """Whether the tool explicitly said *this plan* does not exist.

    Deliberately keyed to the plan number rather than the bare phrase "not
    found". A retro payload reports "1 files in the plan's impact map were not
    found in the graph", which a loose substring match reads as the plan itself
    being missing -- and then fails a tool that found its plan perfectly well.
    """
    return f"plan {plan} not found" in _body(payload).lower()


#: Fields carrying substantive rows across the plan-keyed tools.
_ROW_FIELDS = (
    "directly_referenced",
    "file_overlap_studies",
    "adrs",
    "studies",
    "spikes",
    "results",
    "findings",
    "decisions",
)


def _returned_no_rows(payload: dict[str, Any]) -> bool:
    """Whether every substantive row list in the payload is empty."""
    present = [payload[f] for f in _ROW_FIELDS if isinstance(payload.get(f), list)]
    return bool(present) and all(len(rows) == 0 for rows in present)


def _failed_closed(payload: dict[str, Any], plan: int) -> bool:
    """Whether the tool declined to answer about a plan outside its project.

    Two shapes are acceptable and both are honest: saying the plan is missing,
    or returning no rows. ``scaffold_prior_experiments`` does the latter -- it
    reports ``total_count: 0`` rather than an error -- so demanding a
    not-found message would fail a correctly scoped tool.
    """
    return _says_plan_missing(payload, plan) or _returned_no_rows(payload)


# ---------------------------------------------------------------------------
# The probe: asking one project for the other's plan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", PLAN_KEYED_TOOLS)
@pytest.mark.parametrize("asked_from", [ALPHA, BETA])
def test_a_plan_keyed_tool_refuses_the_other_projects_plan(
    tool: str, asked_from: str, two_project_workspace
):
    """Asking beta for alpha's plan has one correct answer: not found."""
    owned = OWNED[asked_from]
    foreign = owned["foreign_plan"]
    other_token = OWNED[ALPHA if asked_from == BETA else BETA]["token"]

    result = _call(tool, two_project_workspace, asked_from, plan_number=foreign)

    assert other_token not in _body(
        result
    ), f"{tool} asked from {asked_from} for plan {foreign} returned the other project's content"
    assert _failed_closed(result, foreign), (
        f"{tool} asked from {asked_from} for plan {foreign} neither refused nor "
        f"returned an empty result; it must fail closed"
    )


@pytest.mark.parametrize("tool", PLAN_KEYED_TOOLS)
@pytest.mark.parametrize("asked_from", [ALPHA, BETA])
def test_a_plan_keyed_tool_finds_its_own_projects_plan(
    tool: str, asked_from: str, two_project_workspace
):
    """The non-vacuity half.

    Without this, the refusal test above is satisfied by a tool that finds
    nothing ever, and would certify scoping on a surface answering no questions
    at all.
    """
    owned = OWNED[asked_from]

    result = _call(tool, two_project_workspace, asked_from, plan_number=owned["plan"])

    assert not _says_plan_missing(result, owned["plan"]), (
        f"{tool} asked from {asked_from} could not find its own plan "
        f"{owned['plan']}, so the refusal case proves nothing"
    )
    assert _body(result) != _body(
        _call(tool, two_project_workspace, asked_from, plan_number=owned["foreign_plan"])
    ), (
        f"{tool} answers identically for its own plan and a foreign one, so it "
        f"is not distinguishing them at all"
    )


@pytest.mark.parametrize("tool,argument,rows_field", TOPIC_KEYED_TOOLS)
@pytest.mark.parametrize("asked_from", [ALPHA, BETA])
def test_a_topic_keyed_tool_does_not_return_the_other_projects_content(
    tool: str, argument: str, rows_field: str, asked_from: str, two_project_workspace
):
    """Searching for the other project's topic must return no rows.

    The token is deliberately the one word appearing in the other project's
    plans, ADR, spike, study, contract, learning and backlog -- so a tool
    reading any of those from the wrong project is caught regardless of which
    artifact it consults.
    """
    other = ALPHA if asked_from == BETA else BETA
    other_token = OWNED[other]["token"]

    result = _call(tool, two_project_workspace, asked_from, **{argument: other_token})

    assert other_token not in _rows(
        result, rows_field
    ), f"{tool} asked from {asked_from} for {other}'s topic returned {other}'s rows"


@pytest.mark.parametrize("tool,argument,rows_field", TOPIC_KEYED_TOOLS)
@pytest.mark.parametrize("asked_from", [ALPHA, BETA])
def test_a_topic_keyed_tool_finds_its_own_projects_content(
    tool: str, argument: str, rows_field: str, asked_from: str, two_project_workspace
):
    """The non-vacuity half for topic-keyed tools."""
    token = OWNED[asked_from]["token"]

    result = _call(tool, two_project_workspace, asked_from, **{argument: token})

    assert token in _rows(result, rows_field), (
        f"{tool} asked from {asked_from} returned no rows for its own topic, so "
        f"the cross-project case proves nothing"
    )


# ---------------------------------------------------------------------------
# Orientation, which reads governance without being told what to look at
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("asked_from", [ALPHA, BETA])
def test_orient_reports_only_the_asking_projects_state(asked_from: str, two_project_workspace):
    """The session router is the tool most likely to be trusted uncritically."""
    other = ALPHA if asked_from == BETA else BETA

    result = _call("scaffold_orient", two_project_workspace, asked_from)
    text = _body(result)

    assert (
        OWNED[other]["token"] not in text
    ), f"orient asked from {asked_from} surfaced {other}'s content"
    assert (
        f"{OWNED[other]['plan']}-{other}" not in text
    ), f"orient asked from {asked_from} named {other}'s plan file"
    # Non-vacuity: orient must actually be reporting this project's state.
    assert (
        OWNED[asked_from]["token"] in text or str(OWNED[asked_from]["plan"]) in text
    ), f"orient asked from {asked_from} reported nothing about it"


@pytest.mark.parametrize("asked_from", [ALPHA, BETA])
def test_compare_plans_refuses_to_compare_across_projects(asked_from: str, two_project_workspace):
    """Comparing one's own plan against a foreign one must not silently work.

    This is the case where a leak is least visible: the response looks like a
    normal comparison, and nothing in it says the second plan came from another
    project.
    """
    owned = OWNED[asked_from]
    other = ALPHA if asked_from == BETA else BETA

    result = _call(
        "scaffold_compare_plans",
        two_project_workspace,
        asked_from,
        plan_a=owned["plan"],
        plan_b=owned["foreign_plan"],
    )

    assert OWNED[other]["token"] not in _body(result)


# ---------------------------------------------------------------------------
# Proving the suite above would fail if scoping broke
# ---------------------------------------------------------------------------


def test_the_conformance_oracle_rejects_a_genuine_cross_project_answer(
    two_project_workspace,
):
    """Would any of this fail if a tool did leak?

    Scoping here is enforced by namespacing node ids per project, so it cannot
    be disabled by patching a predicate -- which makes it easy to write a suite
    that passes without ever exercising the guarantee. The explicit ``project``
    override crosses the boundary deliberately and yields exactly the payload a
    leaking tool would produce, so running the oracle against it shows the
    oracle can say no.

    This also records something the passing tests do not: the "must not contain
    the other project's token" assertion would *not* catch this leak on its own,
    because a review brief carries titles and paths rather than plan prose. The
    fail-closed assertion is the one doing the work.
    """
    from agentscaffold.mcp.server import _dispatch_tool

    leaked = _dispatch_tool(
        "scaffold_review_context",
        {
            "plan_number": OWNED[ALPHA]["plan"],
            "project": ALPHA,
            "working_path": str(two_project_workspace.source_file(BETA)),
        },
    )

    assert "Plan 101: alpha feature" in _body(leaked), (
        "the override did not actually produce a cross-project payload, so this "
        "proves nothing about the oracle"
    )
    assert not _failed_closed(leaked, OWNED[ALPHA]["plan"]), (
        "the oracle accepted a payload containing another project's plan; every "
        "passing case in this file is therefore worthless"
    )
