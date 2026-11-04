"""Plan 277: doctor checks for guidance reachability, hook liveness and durability."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from agentscaffold import doctor
from agentscaffold.doctor import (
    DoctorContext,
    check_guidance,
    check_guidance_ignored,
    check_guidance_reachable,
    check_hooks_ran,
    user_copy_drift,
)
from agentscaffold.hooks.generators.cursor import INDEX_HOOK_REL_PATH, render_index_hook_script
from agentscaffold.hooks.router import MANIFEST_FILENAME
from agentscaffold.hooks.worker import project_state, record_last_run
from agentscaffold.workspace_registry import register_workspace


def _project(root: Path, config: str = "agents:\n  agents_md: false\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "scaffold.yaml").write_text(config)
    return root.resolve()


def _ctx(root: Path) -> DoctorContext:
    return DoctorContext(project_root=root, mcp_config_path=root / "no-mcp.json")


def _manifest(home: Path, **fields: Any) -> None:
    (home / MANIFEST_FILENAME).write_text(json.dumps(fields))


def _nested(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    project = _project(repo / "services" / "api")
    (project / ".cursor" / "rules").mkdir(parents=True)
    (project / ".cursor" / "rules" / "agentscaffold.mdc").write_text("rule\n")
    (project / ".cursor" / "hooks.json").write_text("{}")
    return project


# ---------------------------------------------------------------------------
# guidance_reachable
# ---------------------------------------------------------------------------


def test_project_at_its_repository_root_is_reachable(tmp_path: Path) -> None:
    project = _project(tmp_path / "repo")
    (project / ".git").mkdir()
    assert check_guidance_reachable(_ctx(project)).status == "ok"


def test_project_below_its_repository_root_is_warned(tmp_path: Path) -> None:
    project = _nested(tmp_path)
    register_workspace(project, name="api")

    result = check_guidance_reachable(_ctx(project))

    assert result.status == "warn"
    assert ".cursor/hooks.json" in result.details
    assert ".cursor/rules/agentscaffold.mdc" in result.details
    assert result.remediation is not None and "--project api" in result.remediation


def test_unregistered_nested_project_is_told_to_register(tmp_path: Path) -> None:
    result = check_guidance_reachable(_ctx(_nested(tmp_path)))
    assert result.status == "warn"
    assert result.remediation is not None and "scaffold project register" in result.remediation


def test_user_scope_install_covers_a_nested_project(
    tmp_path: Path, isolate_agentscaffold_home: Path
) -> None:
    project = _nested(tmp_path)
    register_workspace(project, name="api")
    _manifest(isolate_agentscaffold_home, cursor_plugins={"projects": {"api": "/p"}})

    result = check_guidance_reachable(_ctx(project))

    assert result.status == "ok"
    assert "covers project api" in result.summary


# ---------------------------------------------------------------------------
# durability
# ---------------------------------------------------------------------------


@pytest.fixture()
def ignored_agents_md(monkeypatch: pytest.MonkeyPatch) -> None:
    import agentscaffold.rendering as rendering

    monkeypatch.setattr(rendering, "ignored_guidance_files", lambda root: [root / "AGENTS.md"])


def test_ignored_guidance_warns_when_committed(tmp_path: Path, ignored_agents_md: None) -> None:
    result = check_guidance_ignored(_ctx(_project(tmp_path / "p")))
    assert result.status == "warn"
    assert result.remediation is not None and "durability: local" in result.remediation


def test_durability_local_accepts_ignored_guidance(tmp_path: Path, ignored_agents_md: None) -> None:
    project = _project(tmp_path / "p", "agents:\n  agents_md: false\n  durability: local\n")
    result = check_guidance_ignored(_ctx(project))
    assert result.status == "ok"
    assert "as intended" in result.summary


# ---------------------------------------------------------------------------
# hooks_ran
# ---------------------------------------------------------------------------


def _with_project_hook(project: Path, text: str) -> None:
    script = project / INDEX_HOOK_REL_PATH
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(text)


def _graph(project: Path, *, mtime: float | None = None) -> Path:
    from agentscaffold.config import load_config
    from agentscaffold.paths import resolve_db_path

    db = resolve_db_path(load_config(project / "scaffold.yaml"), start=project)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"")
    if mtime is not None:
        os.utime(db, (mtime, mtime))
    return db


def test_no_hook_installed_is_skipped(tmp_path: Path) -> None:
    assert check_hooks_ran(_ctx(_project(tmp_path / "p"))).status == "skip"


def test_installed_hook_without_a_graph_is_fine(tmp_path: Path) -> None:
    project = _project(tmp_path / "p")
    _with_project_hook(project, render_index_hook_script("scaffold hook"))
    assert check_hooks_ran(_ctx(project)).status == "ok"


def test_installed_hook_that_never_ran_is_warned(tmp_path: Path) -> None:
    project = _project(tmp_path / "p")
    _with_project_hook(project, render_index_hook_script("scaffold hook"))
    _graph(project)

    result = check_hooks_ran(_ctx(project))

    assert result.status == "warn"
    assert "never recorded a run" in result.summary


def test_recent_hook_run_is_reported(tmp_path: Path) -> None:
    project = _project(tmp_path / "p")
    _with_project_hook(project, render_index_hook_script("scaffold hook"))
    _graph(project)
    state, _ = project_state(project)
    record_last_run(state, "cursor-after-edit")

    result = check_hooks_ran(_ctx(project))

    assert result.status == "ok"
    assert "cursor-after-edit" in result.summary


def test_silent_hook_with_a_fresher_graph_is_warned(tmp_path: Path) -> None:
    project = _project(tmp_path / "p")
    _with_project_hook(project, render_index_hook_script("scaffold hook"))
    _graph(project, mtime=time.time())
    state, _ = project_state(project)
    record_last_run(state, "cursor-after-edit", now=time.time() - 30 * 24 * 3600)

    result = check_hooks_ran(_ctx(project))

    assert result.status == "warn"
    assert "has not run since" in result.summary


def test_user_hook_counts_as_installed(tmp_path: Path, isolate_agentscaffold_home: Path) -> None:
    project = _project(tmp_path / "p")
    register_workspace(project, name="p")
    _manifest(isolate_agentscaffold_home, components=["hooks"])
    _graph(project)
    result = check_hooks_ran(_ctx(project))
    assert result.status == "warn"
    assert "user" in result.details[0]


def test_legacy_project_hook_beside_a_user_hook_is_warned(
    tmp_path: Path, isolate_agentscaffold_home: Path
) -> None:
    project = _project(tmp_path / "p")
    register_workspace(project, name="p")
    _manifest(isolate_agentscaffold_home, components=["hooks"])
    _with_project_hook(project, '#!/usr/bin/env bash\nscaffold_bin="scaffold"\n')

    result = check_hooks_ran(_ctx(project))

    assert result.status == "warn"
    assert "different locks" in result.summary
    assert result.remediation is not None and "scaffold agents hooks" in result.remediation


# ---------------------------------------------------------------------------
# user-copy drift
# ---------------------------------------------------------------------------


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_user_copy_drift_reports_missing_and_edited_files(
    tmp_path: Path, isolate_agentscaffold_home: Path
) -> None:
    intact = tmp_path / "intact.mdc"
    intact.write_text("same\n")
    edited = tmp_path / "edited.mdc"
    edited.write_text("changed\n")
    files = {
        str(intact): _sha(b"same\n"),
        str(edited): _sha(b"original\n"),
        str(tmp_path / "gone.mdc"): _sha(b"x"),
    }
    _manifest(isolate_agentscaffold_home, files=files)

    drift = user_copy_drift()

    assert len(drift) == 2
    assert any("edited.mdc: edited" in d for d in drift)
    assert any("gone.mdc: missing" in d for d in drift)


def test_stale_shared_rule_is_reported(tmp_path: Path, isolate_agentscaffold_home: Path) -> None:
    from agentscaffold.agents.user_scope import SHARED_RULE_NAME

    old = tmp_path / SHARED_RULE_NAME
    old.write_text("routing from an older release\n")
    _manifest(isolate_agentscaffold_home, files={str(old): _sha(old.read_bytes())})

    assert user_copy_drift() == [f"{old}: stale (generated by an older AgentScaffold)"]


def test_check_guidance_includes_user_copy_drift(
    tmp_path: Path, isolate_agentscaffold_home: Path
) -> None:
    _manifest(isolate_agentscaffold_home, files={str(tmp_path / "gone.mdc"): "0" * 64})
    result = check_guidance(_ctx(_project(tmp_path / "p")))
    assert result.status == "warn"
    assert result.remediation is not None and "--scope user" in result.remediation


def test_fresh_user_install_has_no_drift(tmp_path: Path, isolate_agentscaffold_home: Path) -> None:
    from agentscaffold.agents.user_scope import Locations, install_user_scope

    project = _project(tmp_path / "p")
    register_workspace(project, name="p")
    install_user_scope(
        hook_command="scaffold-hook",
        clients=["cursor", "claude"],
        locations=Locations(
            home=isolate_agentscaffold_home,
            cursor_home=tmp_path / "c",
            claude_home=tmp_path / "cl",
        ),
    )
    assert user_copy_drift() == []


def test_new_checks_are_registered() -> None:
    names = [check.name for check in doctor.CHECKS]
    assert names.index("guidance_reachable") == names.index("guidance_ignored") + 1
    assert "hooks_ran" in names
