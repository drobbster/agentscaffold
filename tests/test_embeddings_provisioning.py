"""Tests for embedding-model provisioning + offline-graceful degrade (Plan 227, Tier 2a).

These cover the dependency/weight fragility fix: a configurable + workspace-pinned
model, a deliberate ``warm`` provisioning path, a fast readiness probe, and search
degrading to keyword-only (with an actionable reason) when the model is not ready.

All model interactions are stubbed/monkeypatched -- no real weight download.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentscaffold.cli import app
from agentscaffold.graph import embeddings


@pytest.fixture(autouse=True)
def _reset_embed_config():
    """Restore the process-wide embedding config after each test."""
    yield
    embeddings.configure_embeddings("all-MiniLM-L6-v2", None)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def test_search_config_defaults():
    from agentscaffold.config import ScaffoldConfig

    config = ScaffoldConfig()
    assert config.search.embedding_model == "all-MiniLM-L6-v2"
    assert config.search.cache_dir == ".scaffold/models"


# ---------------------------------------------------------------------------
# configure / resolve
# ---------------------------------------------------------------------------


def test_configure_sets_active_model_and_cache(tmp_path: Path):
    cache = tmp_path / "models"
    embeddings.configure_embeddings("custom-model", str(cache))
    assert embeddings._active_model_name() == "custom-model"
    assert embeddings._active_cache_dir() == str(cache)


def test_active_model_name_explicit_overrides_configured():
    embeddings.configure_embeddings("configured-model", None)
    assert embeddings._active_model_name("explicit") == "explicit"
    assert embeddings._active_model_name() == "configured-model"


def test_resolve_cache_dir_relative_is_absolute():
    resolved = embeddings._resolve_cache_dir(".scaffold/models")
    assert resolved is not None
    assert Path(resolved).is_absolute()
    assert resolved.endswith("models")


def test_resolve_cache_dir_none_and_empty():
    assert embeddings._resolve_cache_dir(None) is None
    assert embeddings._resolve_cache_dir("") is None


# ---------------------------------------------------------------------------
# warm_model / model_ready
# ---------------------------------------------------------------------------


def test_warm_model_requires_package(monkeypatch):
    monkeypatch.setattr(embeddings, "_st_available", False)
    with pytest.raises(ImportError, match="agentscaffold\\[search\\]"):
        embeddings.warm_model()


def test_warm_model_loads_and_returns_name(monkeypatch):
    monkeypatch.setattr(embeddings, "_st_available", True)
    calls: dict[str, object] = {}
    monkeypatch.setattr(
        embeddings, "_get_model", lambda m=None, c=None: calls.setdefault("loaded", (m, c))
    )
    name = embeddings.warm_model("my-model")
    assert calls["loaded"] == ("my-model", None)
    assert name == "my-model"


def test_model_ready_false_without_package(monkeypatch):
    monkeypatch.setattr(embeddings, "_st_available", False)
    assert embeddings.model_ready() is False


def test_model_ready_true_when_already_loaded(monkeypatch):
    monkeypatch.setattr(embeddings, "_st_available", True)
    embeddings.configure_embeddings("loaded-model", None)
    embeddings._model_cache[("loaded-model", None)] = object()
    try:
        assert embeddings.model_ready() is True
    finally:
        embeddings._model_cache.pop(("loaded-model", None), None)


# ---------------------------------------------------------------------------
# evaluate_retrieval: offline-graceful degrade when weights not provisioned
# ---------------------------------------------------------------------------


def test_evaluate_retrieval_hybrid_degrades_to_keyword_when_model_not_ready(monkeypatch):
    from agentscaffold.graph import search

    monkeypatch.setattr(embeddings, "_st_available", True)
    monkeypatch.setattr(embeddings, "embeddings_available", lambda store: True)
    monkeypatch.setattr(embeddings, "model_ready", lambda *a, **k: False)

    res = search.evaluate_retrieval(object(), "hybrid")
    assert res["retrieval_status"] == "degraded"
    assert res["retrieval_effective_mode"] == "keyword"
    assert "warm" in res["retrieval_reason"]


def test_evaluate_retrieval_semantic_unavailable_when_model_not_ready(monkeypatch):
    from agentscaffold.graph import search

    monkeypatch.setattr(embeddings, "_st_available", True)
    monkeypatch.setattr(embeddings, "embeddings_available", lambda store: True)
    monkeypatch.setattr(embeddings, "model_ready", lambda *a, **k: False)

    res = search.evaluate_retrieval(object(), "semantic")
    assert res["retrieval_status"] == "unavailable"
    assert res["retrieval_effective_mode"] == "none"
    assert "warm" in res["retrieval_reason"]


def test_evaluate_retrieval_available_when_model_ready(monkeypatch):
    from agentscaffold.graph import search

    monkeypatch.setattr(embeddings, "_st_available", True)
    monkeypatch.setattr(embeddings, "embeddings_available", lambda store: True)
    monkeypatch.setattr(embeddings, "model_ready", lambda *a, **k: True)

    res = search.evaluate_retrieval(object(), "hybrid")
    assert res["retrieval_status"] == "available"
    assert res["retrieval_effective_mode"] == "hybrid"


# ---------------------------------------------------------------------------
# CLI: model-status smoke (thin glue over tested helpers)
# ---------------------------------------------------------------------------


def test_cli_model_status_reports_missing_package(tmp_path, monkeypatch, cli_runner):
    (tmp_path / "scaffold.yaml").write_text("framework:\n  project_name: X\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(embeddings, "_st_available", False)

    result = cli_runner.invoke(app, ["graph", "model-status"])
    assert result.exit_code == 0
    assert "readiness" in result.output.lower()
    assert "agentscaffold[search]" in result.output


def test_cli_warm_reports_missing_package(tmp_path, monkeypatch, cli_runner):
    (tmp_path / "scaffold.yaml").write_text("framework:\n  project_name: X\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(embeddings, "_st_available", False)

    result = cli_runner.invoke(app, ["graph", "warm"])
    assert result.exit_code == 1
    assert "agentscaffold[search]" in result.output
