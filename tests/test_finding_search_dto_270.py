"""Plan 270: ReviewFinding search hits use finding text and plan::N."""

from __future__ import annotations

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.graph.search import hybrid_search


def test_finding_keyword_hit_uses_text_and_plan_path() -> None:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    store.create_node(
        "ReviewFinding",
        {
            "id": "finding::tests",
            "reviewType": "devil",
            "planNumber": 227,
            "severity": "high",
            "category": "correctness",
            "finding": "Governance recall needs a regression test.",
            "resolution": "",
            "status": "open",
        },
    )
    try:
        results = hybrid_search(
            store,
            "governance recall regression",
            mode="keyword",
            tables=["ReviewFinding"],
        )
        assert results
        hit = results[0]
        assert hit.node_type == "ReviewFinding"
        assert "Governance recall" in hit.name
        assert hit.name != "correctness"
        assert hit.path == "plan::227"
        assert hit.path != "high"
    finally:
        store.close()
