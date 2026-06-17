"""Embedding generation scoping tests for Plan 231."""

from __future__ import annotations

from typing import Any

from agentscaffold.graph import embeddings


class _FakeModel:
    def __init__(self) -> None:
        self.encoded: list[str] = []

    def encode(self, texts: list[str], show_progress_bar: bool = False) -> list[list[float]]:
        del show_progress_bar
        self.encoded.extend(texts)
        return [[1.0, 0.0, 0.0] for _ in texts]


class _EmbeddingStore:
    def __init__(self) -> None:
        self.embedded: list[tuple[str, str, str]] = []

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        del params
        if "FROM Function" in sql:
            return [
                {
                    "n.id": "function::src/changed.py::changed",
                    "n.name": "changed",
                    "n.signature": "changed()",
                    "n.filePath": "src/changed.py",
                    "n.startLine": 1,
                    "n.endLine": 1,
                },
                {
                    "n.id": "function::src/unchanged.py::unchanged",
                    "n.name": "unchanged",
                    "n.signature": "unchanged()",
                    "n.filePath": "src/unchanged.py",
                    "n.startLine": 1,
                    "n.endLine": 1,
                },
            ]
        return []

    def query_scalar(self, sql: str, params: dict[str, Any] | None = None) -> int:
        del sql, params
        return 0

    def store_embedding(
        self,
        node_id: str,
        node_type: str,
        embedding: list[float],
        *,
        model: str,
        text_hash: str,
    ) -> None:
        del embedding
        self.embedded.append((node_id, node_type, f"{model}:{text_hash}"))


def test_generate_embeddings_scopes_to_changed_file_paths(monkeypatch) -> None:
    store = _EmbeddingStore()
    model = _FakeModel()
    monkeypatch.setattr(embeddings, "_st_available", True)
    monkeypatch.setattr(embeddings, "_get_model", lambda *_args, **_kwargs: model)

    result = embeddings.generate_embeddings(
        store,
        tables=["Function"],
        file_paths={"src/changed.py"},
    )

    assert result == {"Function": 1}
    assert [node_id for node_id, _node_type, _meta in store.embedded] == [
        "function::src/changed.py::changed"
    ]
    assert len(model.encoded) == 1
    assert "changed" in model.encoded[0]
    assert "unchanged" not in model.encoded[0]
