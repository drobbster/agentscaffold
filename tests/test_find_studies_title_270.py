"""Plan 270: find_studies matches title tokens, not only tags."""

from __future__ import annotations

from agentscaffold.graph.duckpgq_backend import DuckPGQBackend
from agentscaffold.mcp.server import _tool_find_studies


def test_find_studies_hits_title_when_tags_empty() -> None:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    store.create_node(
        "Study",
        {
            "id": "study::memory",
            "studyId": "STU-2026-01-01-memory",
            "title": "Memory architecture notes",
            "tags": "",
            "status": "complete",
            "outcome": "needs_followup",
            "confidence": "high",
            "started": "2026-01-01",
        },
    )
    try:
        result = _tool_find_studies(store, {"topic": "memory architecture"}, {})
        ids = {s.get("studyId") for s in result["studies"]}
        assert "STU-2026-01-01-memory" in ids
        assert result["count"] >= 1
    finally:
        store.close()


def test_find_studies_still_hits_tag_substring() -> None:
    store = DuckPGQBackend(":memory:")
    store.init_schema()
    store.create_node(
        "Study",
        {
            "id": "study::tags",
            "studyId": "STU-2026-01-02-tags",
            "title": "Unrelated title",
            "tags": "memory-architecture,eval",
            "status": "complete",
            "outcome": "needs_followup",
            "confidence": "high",
            "started": "2026-01-02",
        },
    )
    try:
        result = _tool_find_studies(store, {"topic": "memory-architecture"}, {})
        ids = {s.get("studyId") for s in result["studies"]}
        assert "STU-2026-01-02-tags" in ids
    finally:
        store.close()
