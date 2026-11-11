"""Upgrade the install that is running, whatever version it was pinned to."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agentscaffold.upgrade import (
    claude_registration_reminder,
    requirement_from_receipt,
    rewrite_registered_hooks,
    upgrade_argv,
)


def test_upgrade_reminder_only_when_claude_has_no_mcp_component(tmp_path: Path) -> None:
    path = tmp_path / "user-install.json"
    path.write_text(
        '{"clients": ["claude"], "components": ["hooks", "rules"]}\n', encoding="utf-8"
    )
    reminder = claude_registration_reminder(tmp_path)
    assert reminder is not None and "scaffold mcp install --client claude" in reminder

    path.write_text(
        '{"clients": ["claude"], "components": ["hooks", "rules", "mcp"]}\n', encoding="utf-8"
    )
    assert claude_registration_reminder(tmp_path) is None
    path.write_text('{"clients": ["cursor"], "components": ["hooks"]}\n', encoding="utf-8")
    assert claude_registration_reminder(tmp_path) is None


def test_a_uv_tool_pin_is_replaced_with_install_dash_u(tmp_path: Path) -> None:
    receipt = tmp_path / "uv-receipt.toml"
    receipt.write_text(
        '[tool]\nrequirements = [{ name = "agentscaffold", extras = ["all"], '
        'specifier = "==0.12.0" }]\n',
        encoding="utf-8",
    )

    argv = upgrade_argv(tmp_path, uv="/usr/bin/uv", pipx=None)

    assert argv == ["/usr/bin/uv", "tool", "install", "-U", "agentscaffold[all]"]


def test_uv_extras_are_kept_and_a_plain_install_stays_plain(tmp_path: Path) -> None:
    assert requirement_from_receipt('extras = ["mcp", "graph"]') == "agentscaffold[mcp,graph]"
    (tmp_path / "uv-receipt.toml").write_text("[tool]\nrequirements = []\n", encoding="utf-8")

    argv = upgrade_argv(tmp_path, uv="uv", pipx=None)

    assert argv == ["uv", "tool", "install", "-U", "agentscaffold"]


def test_a_uv_tool_without_uv_on_path_cannot_upgrade(tmp_path: Path) -> None:
    (tmp_path / "uv-receipt.toml").write_text("extras = []\n", encoding="utf-8")

    assert upgrade_argv(tmp_path, uv=None, pipx="/usr/bin/pipx") is None


def test_pipx_and_pip_use_their_own_upgraders(tmp_path: Path) -> None:
    pipx_prefix = tmp_path / "pipx" / "venvs" / "agentscaffold"
    pipx_prefix.mkdir(parents=True)
    pip_prefix = tmp_path / "venv"
    pip_prefix.mkdir()

    assert upgrade_argv(pipx_prefix, uv=None, pipx="/usr/bin/pipx") == [
        "/usr/bin/pipx",
        "upgrade",
        "agentscaffold",
    ]
    argv = upgrade_argv(pip_prefix, uv="/usr/bin/uv", pipx="/usr/bin/pipx")
    assert argv is not None
    assert argv[-4:] == ["pip", "install", "-U", "agentscaffold"]


def test_perform_upgrade_reexecs_the_new_binary_to_rewrite_hooks(monkeypatch) -> None:
    from agentscaffold.upgrade import perform_upgrade

    monkeypatch.setattr(
        "agentscaffold.upgrade.upgrade_argv",
        lambda *args, **kwargs: ["uv", "tool", "install", "-U", "agentscaffold"],
    )
    monkeypatch.setattr("agentscaffold.upgrade.this_scaffold", lambda: "/opt/scaffold")
    ran: list[list[str]] = []
    reexec: list[tuple[str, list[str]]] = []

    def run(argv, check):
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    code = perform_upgrade(run=run, execv=lambda binary, argv: reexec.append((binary, argv)))

    assert code == 0
    assert ran == [["uv", "tool", "install", "-U", "agentscaffold"]]
    assert reexec == [("/opt/scaffold", ["/opt/scaffold", "upgrade", "--rewrite-hooks"])]


def test_rewrite_hooks_runs_in_each_registered_root(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    missing = tmp_path / "gone"
    first.mkdir()
    second.mkdir()
    calls: list[tuple[list[str], Path]] = []

    def run(argv, cwd, check):
        calls.append((argv, cwd))
        return subprocess.CompletedProcess(argv, 0 if cwd == first else 1)

    monkeypatch.setattr("agentscaffold.upgrade.this_scaffold", lambda: "/opt/scaffold")

    failed = rewrite_registered_hooks([first, second, missing], run=run)

    assert failed == 2
    assert calls == [
        (["/opt/scaffold", "agents", "hooks"], first),
        (["/opt/scaffold", "agents", "hooks"], second),
    ]
