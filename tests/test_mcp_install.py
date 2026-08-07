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
    find_legacy_entries,
    find_legacy_project_configs,
    is_agentscaffold_entry,
    plan_changes,
    reset_deprecation_warning,
    verify_unrelated_preserved,
    warn_once_about_legacy_entries,
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


def test_install_reports_a_superseded_per_project_config(tmp_path, cli_runner, monkeypatch):
    """The per-project config is redundant the moment the shared entry lands.

    Saying so here is what stops ``scaffold doctor`` reporting, later and out of
    context, a problem the user created by following the quick start (Plan 253).
    """
    target = tmp_path / "mcp.json"
    project = tmp_path / "proj"
    (project / ".cursor").mkdir(parents=True)
    per_project = project / ".cursor" / "mcp.json"
    per_project.write_text(json.dumps({"mcpServers": {"agentscaffold": {"command": "scaffold"}}}))
    monkeypatch.chdir(project)

    result = cli_runner.invoke(app, ["mcp", "install", "--config", str(target)])

    assert result.exit_code == 0
    assert "Superseded" in result.output
    # Reported, never deleted. These files are per-repo and often committed, so
    # removing one on the user's behalf could reach a colleague's checkout.
    assert per_project.exists()


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


# ==========================================================================
# Deprecation path for per-project entries (Plan 249, Step A9)
#
# The contract is: legacy entries keep working, the user is warned once, and
# the warning names the command that fixes it. "Once" is load-bearing -- an
# MCP server that repeated this per call would teach the user to filter it.
# ==========================================================================


@pytest.fixture(autouse=True)
def _reset_warning_latch(tmp_path, monkeypatch):
    """Reset the once-per-process latch and detach from the developer's checkout.

    The chdir is not incidental. Detection scans the working directory, so
    without it a test asserting silence would read whatever repo the suite
    happens to be run from -- and this one really does carry a legacy
    `.cursor/mcp.json`, so three of these tests passed only until the scan
    started working. Same lesson as the registry pollution at Step A8: make the
    environment hermetic in a fixture rather than asking each test to remember.
    """
    neutral = tmp_path / "_cwd"
    neutral.mkdir(exist_ok=True)
    monkeypatch.chdir(neutral)
    reset_deprecation_warning()
    yield
    reset_deprecation_warning()


def _config(tmp_path: Path, servers: dict) -> Path:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}))
    return path


def test_find_legacy_entries_names_per_project_entries():
    document = {
        "mcpServers": {
            "agentscaffold-project-b": {"command": "scaffold"},
            "agentscaffold-project-a": {"command": "scaffold"},
            **FOREIGN,
        }
    }

    assert find_legacy_entries(document) == [
        "agentscaffold-project-a",
        "agentscaffold-project-b",
    ]


def test_the_canonical_entry_is_not_itself_legacy():
    """The single entry we install must never be reported as needing migration."""
    document = {"mcpServers": {CANONICAL_ENTRY_NAME: canonical_entry(), **FOREIGN}}

    assert find_legacy_entries(document) == []


def test_foreign_entries_are_never_treated_as_ours():
    assert find_legacy_entries({"mcpServers": dict(FOREIGN)}) == []


def test_warning_names_the_migration_command(tmp_path, caplog):
    path = _config(tmp_path, {"agentscaffold-project-a": {"command": "scaffold"}})

    with caplog.at_level("WARNING"):
        message = warn_once_about_legacy_entries(path)

    assert message is not None
    assert "scaffold mcp install --migrate" in message
    assert "agentscaffold-project-a" in message
    assert message in caplog.text


def test_the_warning_is_emitted_only_once_per_process(tmp_path):
    path = _config(tmp_path, {"agentscaffold-project-a": {"command": "scaffold"}})

    first = warn_once_about_legacy_entries(path)
    second = warn_once_about_legacy_entries(path)
    third = warn_once_about_legacy_entries(path)

    assert first is not None
    assert second is None
    assert third is None


def test_no_warning_when_only_the_canonical_entry_is_present(tmp_path):
    path = _config(tmp_path, {CANONICAL_ENTRY_NAME: canonical_entry(), **FOREIGN})

    assert warn_once_about_legacy_entries(path) is None


def test_no_warning_when_the_config_is_absent(tmp_path):
    assert warn_once_about_legacy_entries(tmp_path / "nope.json") is None


def test_an_unparseable_config_does_not_raise(tmp_path):
    """A notice must never be able to stop the server from starting.

    `scaffold mcp install` refuses an unparseable config loudly, which is right
    for a command that would write to it. This path only observes, so it stays
    quiet rather than turning the user's hand-edited JSON into a startup crash.
    """
    path = tmp_path / "mcp.json"
    path.write_text("{ not json at all")

    assert warn_once_about_legacy_entries(path) is None


def test_legacy_entries_still_work_after_the_warning(tmp_path):
    """Warning is not removing. Deprecated entries survive until --migrate."""
    legacy = {"agentscaffold-project-a": {"command": "scaffold", "args": ["mcp"]}}
    path = _config(tmp_path, legacy)

    warn_once_about_legacy_entries(path)

    assert json.loads(path.read_text())["mcpServers"] == legacy


# --------------------------------------------------------------------------
# The legacy shape found in the field
#
# Integration verification against this machine (Step A9) showed the unit tests
# above had assumed the wrong shape. The real per-project registrations are not
# `agentscaffold-<project>` entries in the shared user config -- they are per-repo
# `.cursor/mcp.json` files, each holding an entry named plainly `agentscaffold`.
# Detection keyed on the name alone reported "nothing to migrate" on the very
# workspace that motivated this plan.
# --------------------------------------------------------------------------


def _project_config(root: Path, servers: dict) -> Path:
    path = root / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}))
    return path


def test_a_project_scoped_entry_is_legacy_despite_the_canonical_name(tmp_path):
    """Location makes it legacy, not the name."""
    root = tmp_path / "repo"
    _project_config(root, {CANONICAL_ENTRY_NAME: {"command": "scaffold", "args": ["mcp"]}})

    assert find_legacy_project_configs([root]) == [root / ".cursor" / "mcp.json"]


def test_project_configs_without_agentscaffold_are_left_alone(tmp_path):
    root = tmp_path / "repo"
    _project_config(root, dict(FOREIGN))

    assert find_legacy_project_configs([root]) == []


def test_a_project_without_a_config_is_skipped(tmp_path):
    assert find_legacy_project_configs([tmp_path / "no-such-repo"]) == []


def test_an_unparseable_project_config_is_skipped(tmp_path):
    root = tmp_path / "repo"
    (root / ".cursor").mkdir(parents=True)
    (root / ".cursor" / "mcp.json").write_text("{ broken")

    assert find_legacy_project_configs([root]) == []


def test_the_warning_reports_project_scoped_configs(tmp_path):
    root = tmp_path / "repo"
    _project_config(root, {CANONICAL_ENTRY_NAME: {"command": "scaffold"}})
    user_config = _config(tmp_path, dict(FOREIGN))

    message = warn_once_about_legacy_entries(user_config, project_roots=[root])

    assert message is not None
    assert str(root / ".cursor" / "mcp.json") in message


def test_project_scoped_configs_are_not_offered_for_automatic_removal(tmp_path):
    """These files are often committed, so removing entries could reach others.

    The notice tells the user to delete them by hand rather than pointing at
    `--migrate`, which would imply we will do it for them.
    """
    root = tmp_path / "repo"
    _project_config(root, {CANONICAL_ENTRY_NAME: {"command": "scaffold"}})
    user_config = _config(tmp_path, dict(FOREIGN))

    message = warn_once_about_legacy_entries(user_config, project_roots=[root])

    assert "by hand" in message
    assert "--migrate" not in message


def test_both_shapes_are_reported_together(tmp_path):
    root = tmp_path / "repo"
    _project_config(root, {CANONICAL_ENTRY_NAME: {"command": "scaffold"}})
    user_config = _config(tmp_path, {"agentscaffold-project-a": {"command": "scaffold"}})

    message = warn_once_about_legacy_entries(user_config, project_roots=[root])

    assert "agentscaffold-project-a" in message
    assert str(root / ".cursor" / "mcp.json") in message
    assert "--migrate" in message


def test_silence_when_neither_shape_is_present(tmp_path):
    clean = tmp_path / "clean-repo"
    clean.mkdir()
    user_config = _config(tmp_path, {CANONICAL_ENTRY_NAME: canonical_entry()})

    assert warn_once_about_legacy_entries(user_config, project_roots=[clean]) is None


def test_a_missing_user_config_does_not_suppress_project_findings(tmp_path):
    """The two checks are independent.

    Returning early on an absent user config would hide every project-scoped
    entry -- which is the common case, since the single user-level entry does
    not exist until `scaffold mcp install` has been run.
    """
    root = tmp_path / "repo"
    _project_config(root, {CANONICAL_ENTRY_NAME: {"command": "scaffold"}})

    message = warn_once_about_legacy_entries(tmp_path / "absent.json", project_roots=[root])

    assert message is not None


def test_the_working_directory_is_scanned_even_with_an_empty_registry(tmp_path, monkeypatch):
    """The pre-migration user has registered nothing yet.

    Scanning only the registry made the notice fire only after the user had
    already begun migrating -- silent for everyone who still needed telling.
    """
    root = tmp_path / "repo"
    _project_config(root, {CANONICAL_ENTRY_NAME: {"command": "scaffold"}})
    monkeypatch.chdir(root)

    message = warn_once_about_legacy_entries(tmp_path / "absent.json")

    assert message is not None
    assert ".cursor" in message


def test_a_clean_working_directory_stays_silent(tmp_path, monkeypatch):
    clean = tmp_path / "clean"
    clean.mkdir()
    monkeypatch.chdir(clean)

    assert warn_once_about_legacy_entries(tmp_path / "absent.json") is None
