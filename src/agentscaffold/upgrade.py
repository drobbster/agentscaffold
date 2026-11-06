"""Upgrade the install that is running, then point project hooks at it.

``uv tool upgrade`` does not move a tool that was installed with an exact
pin (``agentscaffold==0.12.0``). ``uv tool install -U`` does, and it drops
the pin so the next upgrade can move. A pip or pipx install is upgraded
with that tool. Hooks are rewritten afterwards because they store the
absolute path of the binary that generated them.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_EXTRAS = re.compile(r"""extras\s*=\s*\[([^\]]*)\]""")
_QUOTED = re.compile(r"""["']([^"']+)["']""")


def requirement_from_receipt(text: str) -> str:
    """The agentscaffold requirement, keeping the extras the tool was given."""
    match = _EXTRAS.search(text)
    if match is None:
        return "agentscaffold"
    extras = _QUOTED.findall(match.group(1))
    if not extras:
        return "agentscaffold"
    return "agentscaffold[" + ",".join(extras) + "]"


def upgrade_argv(prefix: Path, *, uv: str | None, pipx: str | None) -> list[str] | None:
    """The installer command for the environment at *prefix*.

    None when the environment is a uv tool or pipx install but that
    program is not available to run.
    """
    receipt = prefix / "uv-receipt.toml"
    if receipt.is_file():
        if uv is None:
            return None
        requirement = requirement_from_receipt(receipt.read_text(encoding="utf-8"))
        return [uv, "tool", "install", "-U", requirement]
    if "pipx" in prefix.parts:
        if pipx is None:
            return None
        return [pipx, "upgrade", "agentscaffold"]
    return [sys.executable, "-m", "pip", "install", "-U", "agentscaffold"]


def registered_project_roots() -> list[Path]:
    """Absolute roots of every project in the user registry."""
    from agentscaffold.workspace_registry import load_registry

    roots: list[Path] = []
    for workspace in load_registry().workspaces:
        for project in workspace.projects:
            roots.append(workspace.project_root(project))
    return roots


def this_scaffold() -> str:
    """The scaffold executable next to the running interpreter, else ``scaffold``."""
    candidate = Path(sys.executable).parent / "scaffold"
    if candidate.is_file():
        return str(candidate)
    return "scaffold"


def rewrite_registered_hooks(roots: list[Path] | None = None, *, run=subprocess.run) -> int:
    """Regenerate hooks in each registered project. Returns the number of failures."""
    return _rewrite(roots if roots is not None else registered_project_roots(), run)


def _rewrite(roots: list[Path], run) -> int:
    binary = this_scaffold()
    failed = 0
    for root in roots:
        if not root.is_dir():
            print(f"skip {root} (not a directory)", file=sys.stderr)
            failed += 1
            continue
        result = run([binary, "agents", "hooks"], cwd=root, check=False)
        if result.returncode != 0:
            failed += 1
    return failed


def perform_upgrade(*, run=subprocess.run, execv=os.execv) -> int:
    """Upgrade this install, then re-exec so the new code rewrites hooks."""
    import shutil

    argv = upgrade_argv(Path(sys.prefix), uv=shutil.which("uv"), pipx=shutil.which("pipx"))
    if argv is None:
        print(
            "This install is managed by uv or pipx, and that program is not on PATH.",
            file=sys.stderr,
        )
        return 1
    result = run(argv, check=False)
    if result.returncode != 0:
        return result.returncode
    binary = this_scaffold()
    execv(binary, [binary, "upgrade", "--rewrite-hooks"])
    return 0  # pragma: no cover - execv does not return
