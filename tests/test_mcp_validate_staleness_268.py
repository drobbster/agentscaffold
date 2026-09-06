"""Plan 268: scaffold_validate staleness must use the call's project root."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import agentscaffold.graph.verify as verify_mod
from agentscaffold.active_root import active_root
from agentscaffold.mcp.server import _tool_validate


def test_validate_staleness_uses_active_root(tmp_path: Path, monkeypatch: Any) -> None:
    launch = tmp_path / "launch"
    project = tmp_path / "project"
    launch.mkdir()
    project.mkdir()
    monkeypatch.chdir(launch)

    captured: list[Path] = []

    def fake_verify(store: object, root: Path) -> dict[str, str]:
        captured.append(Path(root).resolve())
        return {"health": "GOOD"}

    monkeypatch.setattr(verify_mod, "verify_graph", fake_verify)

    with active_root(project):
        result = _tool_validate(object(), {"check": "staleness"}, {})

    assert captured == [project.resolve()]
    assert result["report"]["health"] == "GOOD"
