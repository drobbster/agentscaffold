"""Tests for ``scaffold doctor --tools``.

The command answers a question no unit test can answer for a user: *do the tools
work in my installation, right now?* That makes its own failure modes the
interesting ones. A probe that reports a healthy tool as broken sends people
chasing nothing; one that reports a broken tool as healthy is worse, because the
whole point is to be believed.

Three behaviours carry most of that weight and are tested hardest here: writes
never touch real governance data unless asked, a graph held by another process
reads as *busy* rather than *broken*, and a tool that genuinely fails is
reported as failing rather than swallowed.
"""

from __future__ import annotations

import pytest

from agentscaffold.doctor import DoctorContext
from agentscaffold.doctor_tools import ToolProbe, probe_tools
from agentscaffold.mcp.registry import tool_names


@pytest.fixture()
def context(two_project_workspace):
    return DoctorContext(
        project_root=two_project_workspace.alpha,
        mcp_config_path=two_project_workspace.root / "mcp.json",
    ), two_project_workspace


def test_every_registered_tool_is_reported(context):
    """A tool missing from the table is a tool nobody knows is broken."""
    doctor_context, _ = context
    probes = probe_tools(doctor_context)

    assert {p.name for p in probes} == set(
        tool_names()
    ), f"table does not cover the registry; missing={set(tool_names()) - {p.name for p in probes}}"


def test_write_tools_are_skipped_by_default(context):
    """Read-only default, asserted on the *reason* and not just the status.

    A skip that happens because the tool errored looks identical to a deliberate
    one unless the reason is checked.
    """
    from agentscaffold.mcp.registry import WRITE_TOOLS

    doctor_context, _ = context
    by_name = {p.name: p for p in probe_tools(doctor_context)}

    for name in WRITE_TOOLS:
        probe = by_name[name]
        assert probe.status == "skip", f"{name} ran without --include-writes ({probe.status})"
        assert (
            "write" in (probe.detail or "").lower()
        ), f"{name} was skipped without saying it was skipped for being a write: {probe.detail}"


def test_read_tools_actually_run_by_default(context):
    """The complement of the skip test, and the one that catches a vacuous pass.

    A probe that skipped *everything* would satisfy the test above perfectly.
    """
    doctor_context, _ = context
    probes = probe_tools(doctor_context)
    ran = [p for p in probes if p.status in {"ok", "fail"}]

    assert len(ran) >= 20, f"only {len(ran)} tools actually ran; the rest were skipped"
    assert any(p.name == "scaffold_context" for p in ran)


def test_include_writes_does_not_touch_the_real_project(context, tmp_path):
    """Writes go to a scratch project or they do not go at all.

    The command is a diagnostic. A diagnostic that leaves findings behind in the
    governance record has changed the thing it was asked to measure.
    """
    doctor_context, workspace = context

    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    store = DuckPGQBackend(workspace.db_path)
    try:
        before = store.query("SELECT count(*) AS n FROM ReviewFinding")[0]["n"]
    finally:
        store.close()

    probes = probe_tools(doctor_context, include_writes=True)
    assert any(
        p.name == "scaffold_record_finding" and p.status != "skip" for p in probes
    ), "--include-writes did not exercise any write tool"

    store = DuckPGQBackend(workspace.db_path)
    try:
        after = store.query("SELECT count(*) AS n FROM ReviewFinding")[0]["n"]
    finally:
        store.close()

    assert (
        after == before
    ), f"--include-writes wrote {after - before} findings into the real project's graph"


def test_a_busy_graph_reports_as_busy_not_as_a_broken_tool(context, monkeypatch):
    """The distinction the Step A0 spike was run to make possible.

    Another process holding the graph is normal and transient -- an indexing run
    in the next terminal. Reporting it as a failed tool would make the command
    cry wolf during exactly the routine operation people run it around.
    """
    from agentscaffold.graph import GraphLockError

    doctor_context, _ = context

    def held(*args, **kwargs):
        raise GraphLockError("another process holds the graph")

    monkeypatch.setattr("agentscaffold.doctor_tools._invoke", held)
    probes = probe_tools(doctor_context)
    ran = [p for p in probes if p.status != "skip"]

    assert ran, "nothing ran, so the busy path was never exercised"
    assert all(p.status == "busy" for p in ran), (
        f"a held graph was reported as something other than busy: "
        f"{[(p.name, p.status) for p in ran if p.status != 'busy']}"
    )
    assert all(
        "retry" in (p.detail or "").lower() for p in ran
    ), "busy result does not tell the user to retry"


def test_a_genuinely_broken_tool_is_reported_as_failing(context, monkeypatch):
    """The probe must be capable of reporting bad news (L249-14).

    Without this, every green run is ambiguous between "all tools work" and
    "the probe cannot tell".
    """
    doctor_context, _ = context

    def broken(*args, **kwargs):
        raise RuntimeError("tool exploded")

    monkeypatch.setattr("agentscaffold.doctor_tools._invoke", broken)
    probes = [p for p in probe_tools(doctor_context) if p.status != "skip"]

    assert probes, "nothing ran"
    assert all(p.status == "fail" for p in probes)
    assert any(
        "exploded" in (p.detail or "") for p in probes
    ), "failure detail does not carry the underlying error"


def test_one_broken_tool_does_not_hide_the_others(context, monkeypatch):
    """Per-tool isolation: the table is the deliverable, not the first error."""
    doctor_context, _ = context
    real = None

    from agentscaffold import doctor_tools

    real = doctor_tools._invoke

    def sometimes(name, *args, **kwargs):
        if name == "scaffold_context":
            raise RuntimeError("only this one is broken")
        return real(name, *args, **kwargs)

    monkeypatch.setattr("agentscaffold.doctor_tools._invoke", sometimes)
    by_name = {p.name: p for p in probe_tools(doctor_context)}

    assert by_name["scaffold_context"].status == "fail"
    assert by_name["scaffold_stats"].status == "ok", "one broken tool took down an unrelated one"


def test_probe_results_are_ordered_like_the_registry(context):
    """Stable output, so two runs can be diffed."""
    doctor_context, _ = context
    assert [p.name for p in probe_tools(doctor_context)] == list(tool_names())


def test_the_cli_exposes_the_table_and_stays_zero_exit_when_healthy(context):
    """``doctor`` is safe in a shell profile; ``--strict`` is the CI gate."""
    from typer.testing import CliRunner

    from agentscaffold.cli import app

    doctor_context, workspace = context
    result = CliRunner().invoke(app, ["doctor", "--tools", "--project-root", str(workspace.alpha)])

    assert result.exit_code == 0, result.output
    assert "scaffold_context" in result.output, result.output


def test_tool_probes_are_typed_records_not_free_text():
    """The table has to be machine-readable for CI to gate on it."""
    probe = ToolProbe(name="x", status="ok", detail="fine", elapsed_ms=1.0)
    assert probe.status in {"ok", "fail", "skip", "busy"}
