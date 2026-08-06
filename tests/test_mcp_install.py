"""Tests for ``scaffold mcp install`` (Plan 249, Step A8).

Written before the installer exists. The command rewrites a *shared* client
config that the user also maintains by hand and that other tools register into,
so most of what follows is about not damaging things we do not own (threat
model, Vector 6).

The central control is the pre-write verification. The threat model originally
asked for unrelated entries to survive "byte-for-byte", which no parse-and-
serialise implementation can honour -- re-serialising reformats the whole
document. The wording was amended at this step to the property that was actually
being protected: no unrelated entry's *content* changes, enforced by comparing
the candidate document against the original before writing and refusing if any
differs. `test_verifier_refuses_when_an_unrelated_entry_would_change` exercises
that guard directly, because it must hold even if the planning code above it is
one day rewritten wrongly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscaffold.cli import app
from agentscaffold.mcp.install import (
    CANONICAL_ENTRY_NAME,
    McpConfigError,
    canonical_entry,
    is_agentscaffold_entry,
    plan_changes,
    verify_unrelated_preserved,
)

FOREIGN = {
    "postgres": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-postgres"]},
    "tipranks": {"url": "https://example.invalid/mcp", "headers": {"x-key": "secret"}},
}


def _write(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


# --------------------------------------------------------------------------
# The entry itself
# --------------------------------------------------------------------------


def test_canonical_entry_has_no_cd_binding_or_interpreter_path():
    """The entry must survive a venv rebuild and a different machine.

    The observed real-world entry pinned an absolute venv path, which breaks
    silently when the venv is rebuilt; and a `cd` binding is what forced one
    server per project in the first place. `scaffold` resolves via PATH, which
    is also how it resolves as `scaffold.exe` on Windows.
    """
    entry = canonical_entry()

    assert entry == {"command": "scaffold", "args": ["mcp"]}
    serialised = json.dumps(entry)
    assert "cd " not in serialised
    assert "/" not in entry["command"]
    assert "venv" not in serialised


def test_entry_ownership_recognises_per_project_variants():
    """Migration has to find legacy entries whatever they were named."""
    assert is_agentscaffold_entry("agentscaffold")
    assert is_agentscaffold_entry("agentscaffold-project-b")
    assert is_agentscaffold_entry("agentscaffold_alpha")
    assert not is_agentscaffold_entry("postgres")
    assert not is_agentscaffold_entry("my-agent-scaffolding")


# --------------------------------------------------------------------------
# Creating and updating the config
# --------------------------------------------------------------------------


def test_install_creates_the_config_when_absent(tmp_path, cli_runner):
    target = tmp_path / ".cursor" / "mcp.json"

    result = cli_runner.invoke(app, ["mcp", "install", "--config", str(target)])

    assert result.exit_code == 0, result.output
    doc = json.loads(target.read_text())
    assert doc["mcpServers"] == {CANONICAL_ENTRY_NAME: canonical_entry()}


def test_install_is_idempotent_and_writes_zero_bytes_when_unchanged(tmp_path, cli_runner):
    """Re-running with nothing to do must not touch the file at all.

    Guarantee 6 in the plan: a no-op reports "no changes" and writes zero bytes.
    Comparing mtime catches a rewrite that happens to produce identical content,
    which would still churn the user's file and any watcher on it.
    """
    target = tmp_path / "mcp.json"
    assert cli_runner.invoke(app, ["mcp", "install", "--config", str(target)]).exit_code == 0
    before_bytes = target.read_bytes()
    before_mtime = target.stat().st_mtime_ns

    again = cli_runner.invoke(app, ["mcp", "install", "--config", str(target)])

    assert again.exit_code == 0, again.output
    assert "no change" in again.output.lower()
    assert target.read_bytes() == before_bytes
    assert target.stat().st_mtime_ns == before_mtime


def test_install_preserves_unrelated_servers(tmp_path, cli_runner):
    target = _write(tmp_path / "mcp.json", {"mcpServers": dict(FOREIGN)})

    result = cli_runner.invoke(app, ["mcp", "install", "--config", str(target)])

    assert result.exit_code == 0, result.output
    doc = json.loads(target.read_text())
    assert doc["mcpServers"]["postgres"] == FOREIGN["postgres"]
    assert doc["mcpServers"]["tipranks"] == FOREIGN["tipranks"]
    assert doc["mcpServers"][CANONICAL_ENTRY_NAME] == canonical_entry()


def test_install_preserves_unrelated_top_level_keys(tmp_path, cli_runner):
    """Clients keep their own settings alongside mcpServers."""
    target = _write(
        tmp_path / "mcp.json",
        {"mcpServers": dict(FOREIGN), "someClientSetting": {"theme": "dark"}},
    )

    assert cli_runner.invoke(app, ["mcp", "install", "--config", str(target)]).exit_code == 0

    doc = json.loads(target.read_text())
    assert doc["someClientSetting"] == {"theme": "dark"}


def test_install_handles_a_config_with_no_mcp_servers_key(tmp_path, cli_runner):
    target = _write(tmp_path / "mcp.json", {"someClientSetting": 1})

    assert cli_runner.invoke(app, ["mcp", "install", "--config", str(target)]).exit_code == 0

    doc = json.loads(target.read_text())
    assert doc["mcpServers"] == {CANONICAL_ENTRY_NAME: canonical_entry()}
    assert doc["someClientSetting"] == 1


# --------------------------------------------------------------------------
# Migration of legacy per-project entries
# --------------------------------------------------------------------------


def test_plain_install_leaves_legacy_entries_alone(tmp_path, cli_runner):
    """Per-project entries keep working through the deprecation window.

    Removing them is what `--migrate` is for. A plain install that silently
    dropped them would break a working setup on what looks like a routine
    upgrade.
    """
    target = _write(
        tmp_path / "mcp.json",
        {
            "mcpServers": {
                "agentscaffold-project-a": {"command": "/old/path/scaffold", "args": ["mcp"]},
                **FOREIGN,
            }
        },
    )

    result = cli_runner.invoke(app, ["mcp", "install", "--config", str(target)])

    assert result.exit_code == 0, result.output
    servers = json.loads(target.read_text())["mcpServers"]
    assert "agentscaffold-project-a" in servers
    assert servers[CANONICAL_ENTRY_NAME] == canonical_entry()
    # ...and it says so, because a silent deprecation is not a deprecation.
    assert "migrate" in result.output.lower()


def test_migrate_collapses_legacy_entries_into_one(tmp_path, cli_runner):
    target = _write(
        tmp_path / "mcp.json",
        {
            "mcpServers": {
                "agentscaffold-project-a": {"command": "/old/scaffold", "args": ["mcp"]},
                "agentscaffold-project-b": {"command": "/old/scaffold", "args": ["mcp"]},
                **FOREIGN,
            }
        },
    )

    result = cli_runner.invoke(app, ["mcp", "install", "--config", str(target), "--migrate"])

    assert result.exit_code == 0, result.output
    servers = json.loads(target.read_text())["mcpServers"]
    assert [k for k in servers if is_agentscaffold_entry(k)] == [CANONICAL_ENTRY_NAME]
    assert servers["postgres"] == FOREIGN["postgres"]
    assert servers["tipranks"] == FOREIGN["tipranks"]


def test_migrate_backs_up_the_prior_file(tmp_path, cli_runner):
    """The user must be able to get their old config back."""
    original = {
        "mcpServers": {
            "agentscaffold-project-a": {"command": "/old/scaffold", "args": ["mcp"]},
            **FOREIGN,
        }
    }
    target = _write(tmp_path / "mcp.json", original)
    before = target.read_bytes()

    assert (
        cli_runner.invoke(app, ["mcp", "install", "--config", str(target), "--migrate"]).exit_code
        == 0
    )

    backups = list(tmp_path.glob("mcp.json.bak*"))
    assert len(backups) == 1, f"expected exactly one backup, got {backups}"
    assert backups[0].read_bytes() == before


# --------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------


def test_dry_run_writes_nothing_but_shows_the_change(tmp_path, cli_runner):
    target = _write(tmp_path / "mcp.json", {"mcpServers": dict(FOREIGN)})
    before = target.read_bytes()

    result = cli_runner.invoke(app, ["mcp", "install", "--config", str(target), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert target.read_bytes() == before
    assert CANONICAL_ENTRY_NAME in result.output
    assert not list(tmp_path.glob("*.bak*"))


def test_dry_run_on_an_absent_config_reports_what_would_be_created(tmp_path, cli_runner):
    target = tmp_path / ".cursor" / "mcp.json"

    result = cli_runner.invoke(app, ["mcp", "install", "--config", str(target), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert not target.exists()


# --------------------------------------------------------------------------
# Refusing to damage what we cannot understand
# --------------------------------------------------------------------------


def test_unparseable_config_is_refused_not_rewritten(tmp_path, cli_runner):
    """A JSONC or hand-edited config must be left exactly as it is.

    Guessing at a config we cannot parse is how unrelated servers get destroyed,
    so the command refuses and hands the user the entry to paste instead.
    """
    target = tmp_path / "mcp.json"
    target.write_text('{\n  // a comment Cursor tolerates\n  "mcpServers": {}\n}\n')
    before = target.read_bytes()

    result = cli_runner.invoke(app, ["mcp", "install", "--config", str(target)])

    assert result.exit_code == 1
    assert target.read_bytes() == before
    assert not list(tmp_path.glob("*.bak*"))
    # The user is not left stuck: the entry to add by hand is printed.
    assert "scaffold" in result.output
    assert CANONICAL_ENTRY_NAME in result.output


def test_a_non_object_config_is_refused(tmp_path, cli_runner):
    target = tmp_path / "mcp.json"
    target.write_text("[1, 2, 3]\n")
    before = target.read_bytes()

    result = cli_runner.invoke(app, ["mcp", "install", "--config", str(target)])

    assert result.exit_code == 1
    assert target.read_bytes() == before


def test_a_non_object_mcp_servers_value_is_refused(tmp_path, cli_runner):
    target = _write(tmp_path / "mcp.json", {"mcpServers": ["not", "a", "mapping"]})
    before = target.read_bytes()

    result = cli_runner.invoke(app, ["mcp", "install", "--config", str(target)])

    assert result.exit_code == 1
    assert target.read_bytes() == before


# --------------------------------------------------------------------------
# The pre-write verification guard
# --------------------------------------------------------------------------


def test_verifier_accepts_a_document_that_only_changes_our_own_entry():
    original = {"mcpServers": {**FOREIGN, "agentscaffold": {"command": "old", "args": []}}}
    candidate = {"mcpServers": {**FOREIGN, "agentscaffold": canonical_entry()}}

    verify_unrelated_preserved(original, candidate)  # must not raise


def test_verifier_refuses_when_an_unrelated_entry_would_change():
    """The guard is the control, so it is tested independently of the planner.

    It has to hold even if the code that builds the candidate document is later
    rewritten incorrectly -- that is the whole point of checking the output
    rather than trusting the process.
    """
    original = {"mcpServers": dict(FOREIGN)}
    candidate = {
        "mcpServers": {
            **FOREIGN,
            "postgres": {"command": "npx", "args": ["--something-else"]},
            "agentscaffold": canonical_entry(),
        }
    }

    with pytest.raises(McpConfigError) as excinfo:
        verify_unrelated_preserved(original, candidate)
    assert "postgres" in str(excinfo.value)


def test_verifier_refuses_when_an_unrelated_entry_would_disappear():
    original = {"mcpServers": dict(FOREIGN)}
    candidate = {"mcpServers": {"agentscaffold": canonical_entry()}}

    with pytest.raises(McpConfigError) as excinfo:
        verify_unrelated_preserved(original, candidate)
    assert "postgres" in str(excinfo.value) or "tipranks" in str(excinfo.value)


def test_verifier_refuses_when_an_unrelated_top_level_key_would_change():
    original = {"mcpServers": {}, "someClientSetting": {"theme": "dark"}}
    candidate = {"mcpServers": {"agentscaffold": canonical_entry()}}

    with pytest.raises(McpConfigError):
        verify_unrelated_preserved(original, candidate)


# --------------------------------------------------------------------------
# Planning, independent of the CLI
# --------------------------------------------------------------------------


def test_plan_reports_no_change_when_already_correct():
    original = {"mcpServers": {"agentscaffold": canonical_entry()}}

    plan = plan_changes(original, migrate=False)

    assert not plan.changed
    assert plan.removed == []


def test_plan_reports_legacy_entries_without_migrate():
    original = {
        "mcpServers": {
            "agentscaffold": canonical_entry(),
            "agentscaffold-project-a": {"command": "x", "args": []},
        }
    }

    plan = plan_changes(original, migrate=False)

    assert not plan.changed
    assert plan.legacy == ["agentscaffold-project-a"]
    assert plan.removed == []


def test_plan_removes_legacy_entries_with_migrate():
    original = {
        "mcpServers": {
            "agentscaffold": canonical_entry(),
            "agentscaffold-project-a": {"command": "x", "args": []},
        }
    }

    plan = plan_changes(original, migrate=True)

    assert plan.changed
    assert plan.removed == ["agentscaffold-project-a"]
    assert plan.document["mcpServers"] == {"agentscaffold": canonical_entry()}
