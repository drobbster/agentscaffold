"""Tests for env-aware db_path resolution (Plan 223)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentscaffold.config import ScaffoldConfig, load_config
from agentscaffold.paths import DB_PATH_ENV_VAR, resolve_db_path


def _config(tmp_path: Path, db_path: str) -> ScaffoldConfig:
    (tmp_path / "scaffold.yaml").write_text(
        yaml.safe_dump({"framework": {"project_name": "t"}, "graph": {"db_path": db_path}})
    )
    return load_config(tmp_path / "scaffold.yaml")


def test_relative_db_path_joins_root(tmp_path: Path) -> None:
    cfg = _config(tmp_path, ".scaffold/graph.duckdb")
    assert resolve_db_path(cfg, start=tmp_path) == tmp_path / ".scaffold/graph.duckdb"


def test_absolute_db_path_is_honored(tmp_path: Path) -> None:
    abs_db = tmp_path / "abs" / "graph.duckdb"
    cfg = _config(tmp_path, str(abs_db))
    assert resolve_db_path(cfg, start=tmp_path / "ignored") == abs_db


def test_env_override_wins(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "scratch" / "graph.duckdb"
    monkeypatch.setenv(DB_PATH_ENV_VAR, str(override))
    cfg = _config(tmp_path, ".scaffold/graph.duckdb")
    assert resolve_db_path(cfg, start=tmp_path) == override


def test_env_placeholder_expansion(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MY_CACHE_DIR", str(tmp_path / "cache"))
    cfg = _config(tmp_path, "${MY_CACHE_DIR}/graph.duckdb")
    assert resolve_db_path(cfg, start=tmp_path) == tmp_path / "cache" / "graph.duckdb"


def test_env_override_relative_joins_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(DB_PATH_ENV_VAR, "var/graph.duckdb")
    cfg = _config(tmp_path, ".scaffold/graph.duckdb")
    assert resolve_db_path(cfg, start=tmp_path) == tmp_path / "var/graph.duckdb"


def test_tilde_expansion(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    cfg = _config(tmp_path, "~/agentscaffold/graph.duckdb")
    assert resolve_db_path(cfg, start=tmp_path) == tmp_path / "home" / "agentscaffold/graph.duckdb"


def test_none_config_uses_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(DB_PATH_ENV_VAR, raising=False)
    resolved = resolve_db_path(None, start=tmp_path)
    assert resolved == tmp_path / ".scaffold/graph.duckdb"


def test_unset_env_placeholder_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEFINITELY_UNSET_CACHE_VAR", raising=False)
    cfg = _config(tmp_path, "${DEFINITELY_UNSET_CACHE_VAR}/graph.duckdb")
    with pytest.raises(ValueError, match="not set"):
        resolve_db_path(cfg, start=tmp_path)
