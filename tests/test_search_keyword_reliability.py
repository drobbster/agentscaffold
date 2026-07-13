"""Plan 243: keyword search must find symbols outside the old LIMIT window.

Regression for the blind ``SELECT ... LIMIT top_k*4`` scan that missed
symbols on large graphs (e.g. rebellion ``normalize_feeds`` returned 0 hits
while ``scaffold_context`` resolved the same name).
"""

from __future__ import annotations

from typing import Any

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend  # noqa: E402
from agentscaffold.graph.search import hybrid_search  # noqa: E402

_TARGET_NAME = "normalize_feeds_unique_xyz"
# Old path: top_k=5 -> keyword limit=10 -> SQL LIMIT 20 per table.
_DUMMY_COUNT = 80


def _func_props(i: int, *, name: str | None = None) -> dict[str, Any]:
    fname = name or f"dummy_fn_{i:04d}"
    return {
        "id": f"fn::pad::{fname}",
        "name": fname,
        "filePath": f"src/pad/{fname}.py",
        "startLine": 1,
        "endLine": 5,
        "isExported": True,
        "paramCount": 0,
        "signature": f"{fname}()",
    }


@pytest.fixture()
def large_function_store() -> Any:
    """Store with many Function rows, then a uniquely named target at the end."""
    s = DuckPGQBackend(":memory:")
    s.init_schema()
    s.create_node(
        "File",
        {
            "id": "file::src/pad/target.py",
            "path": "src/pad/target.py",
            "language": "python",
            "size": 10,
            "lastModified": "2026-01-01",
            "lineCount": 5,
            "contentHash": "pad",
        },
    )
    for i in range(_DUMMY_COUNT):
        s.create_node("Function", _func_props(i))
    s.create_node("Function", _func_props(_DUMMY_COUNT, name=_TARGET_NAME))
    yield s
    s.close()


def test_keyword_finds_symbol_outside_limit_window(large_function_store: Any) -> None:
    results = hybrid_search(
        large_function_store,
        _TARGET_NAME,
        mode="keyword",
        top_k=5,
    )
    names = [r.name for r in results]
    assert _TARGET_NAME in names, f"expected {_TARGET_NAME} in {names}"
    assert results[0].source == "keyword"
    assert results[0].score > 0


def test_hybrid_without_embeddings_still_finds_keyword_hit(
    large_function_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hybrid must degrade to working keyword hits when embeddings are absent."""
    from agentscaffold.graph import embeddings as emb

    monkeypatch.setattr(emb, "embeddings_available", lambda _store: False)

    results = hybrid_search(
        large_function_store,
        _TARGET_NAME,
        mode="hybrid",
        top_k=5,
    )
    assert any(r.name == _TARGET_NAME for r in results)


def test_keyword_multi_token_and_apostrophe(large_function_store: Any) -> None:
    """ILIKE predicates must escape quotes and still match multi-token queries."""
    s = large_function_store
    s.create_node(
        "Function",
        {
            "id": "fn::pad::o_reilly_parse",
            "name": "o'reilly_parse",
            "filePath": "src/pad/oreilly.py",
            "startLine": 1,
            "endLine": 3,
            "isExported": True,
            "paramCount": 0,
            "signature": "o'reilly_parse()",
        },
    )
    results = hybrid_search(s, "o'reilly_parse", mode="keyword", top_k=5)
    assert any(r.name == "o'reilly_parse" for r in results)

    multi = hybrid_search(s, "normalize feeds unique", mode="keyword", top_k=10)
    assert any(_TARGET_NAME in r.name or "normalize" in r.name.lower() for r in multi)
