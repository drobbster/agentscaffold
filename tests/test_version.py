"""CLI version command behavior tests."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import agentscaffold.cli as cli_mod
from agentscaffold.cli import app


def test_version_prefers_installed_distribution(
    monkeypatch,
    cli_runner,
) -> None:
    """Version command should prefer installed package metadata."""
    monkeypatch.setattr(cli_mod, "package_version", lambda _: "9.9.9")

    result = cli_runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "agentscaffold 9.9.9" in result.output


def test_version_falls_back_when_metadata_missing(
    monkeypatch,
    cli_runner,
) -> None:
    """Fallback to module version when package metadata is unavailable."""

    def _raise_not_found(_: str) -> str:
        raise PackageNotFoundError()

    monkeypatch.setattr(cli_mod, "package_version", _raise_not_found)
    monkeypatch.setattr(cli_mod, "__version__", "fallback-version")

    result = cli_runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "agentscaffold fallback-version" in result.output
