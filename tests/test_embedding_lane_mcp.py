"""MCP embedding lane metadata tests for Plan 232."""

from __future__ import annotations

from pathlib import Path

from agentscaffold.config import GraphConfig, ScaffoldConfig
from agentscaffold.mcp import server


def _config(tmp_path: Path, *, policy: str = "idle") -> ScaffoldConfig:
    cfg = ScaffoldConfig()
    cfg.graph = GraphConfig(
        db_path=str(tmp_path / ".scaffold" / "graph.duckdb"),
        async_embeddings=policy,
    )
    return cfg


def test_embedding_lane_schedules_when_retrieval_is_degraded(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def _runtime_state(root: Path, config: ScaffoldConfig) -> dict[str, object]:
        del root, config
        return {"embedding_policy": "idle", "embedding_state": "idle"}

    def _schedule(
        root: Path,
        config: ScaffoldConfig,
        *,
        reason: str,
        file_paths: set[str] | None = None,
    ) -> dict[str, object]:
        del root, config, file_paths
        calls.append(reason)
        return {"embedding_triggered": True, "embedding_schedule_reason": "scheduled"}

    monkeypatch.setattr(
        "agentscaffold.graph.embedding_scheduler.embedding_runtime_state",
        _runtime_state,
    )
    monkeypatch.setattr(
        "agentscaffold.graph.embedding_scheduler.maybe_schedule_async_embeddings",
        _schedule,
    )

    meta = server._maybe_schedule_embedding_lane(
        tmp_path,
        _config(tmp_path),
        {
            "retrieval_status": "degraded",
            "retrieval_reason": "no embeddings indexed",
        },
    )

    assert meta["embedding_triggered"] is True
    assert meta["embedding_schedule_reason"] == "scheduled"
    assert calls == ["no embeddings indexed"]


def test_embedding_lane_does_not_schedule_when_retrieval_is_healthy(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def _runtime_state(root: Path, config: ScaffoldConfig) -> dict[str, object]:
        del root, config
        return {"embedding_policy": "idle", "embedding_state": "idle"}

    monkeypatch.setattr(
        "agentscaffold.graph.embedding_scheduler.embedding_runtime_state",
        _runtime_state,
    )

    meta = server._maybe_schedule_embedding_lane(
        tmp_path,
        _config(tmp_path),
        {"retrieval_status": "ok", "retrieval_reason": "semantic ready"},
    )

    assert meta["embedding_triggered"] is False
    assert meta["embedding_schedule_reason"] == "retrieval_not_degraded"
