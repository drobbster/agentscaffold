"""Tests for BacklogItem CRUD and MCP tool integration (Plan 151)."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    """In-memory DuckPGQBackend with schema initialised."""
    from agentscaffold.graph.duckpgq_backend import DuckPGQBackend

    s = DuckPGQBackend(":memory:")
    s.init_schema()
    yield s
    s.close()


@pytest.fixture()
def store_with_plan(store):
    """Store with a Plan node pre-inserted so BACKLOG_ITEM_OF edges can form."""
    store.execute(
        "INSERT INTO Plan VALUES ('plan::151', 151, 'Graph Write Completeness',"
        " 'in_progress', 'feature', '', '2026-03-01', '2026-03-01', NULL, '')"
    )
    return store


# ---------------------------------------------------------------------------
# record_backlog_item
# ---------------------------------------------------------------------------


def test_record_backlog_item_returns_id(store):
    from agentscaffold.graph.backlog import record_backlog_item

    result = record_backlog_item(store, plan_number=151, title="Add batch findings API")
    assert result["id"].startswith("bi::")
    assert result["status"] == "open"
    assert result["plan_number"] == 151


def test_record_backlog_item_defaults(store):
    from agentscaffold.graph.backlog import record_backlog_item

    result = record_backlog_item(store, plan_number=151, title="Some item")
    assert result["priority"] == "P3"


def test_record_backlog_item_custom_fields(store):
    from agentscaffold.graph.backlog import record_backlog_item

    result = record_backlog_item(
        store,
        plan_number=151,
        title="High priority item",
        priority="P1",
        effort="Small (2h)",
        source="DA Future Regret",
        status="open",
    )
    assert result["priority"] == "P1"
    assert result["status"] == "open"


def test_record_backlog_item_persists_to_db(store):
    from agentscaffold.graph.backlog import record_backlog_item

    result = record_backlog_item(store, plan_number=151, title="Persisted item")
    item_id = result["id"]

    rows = store.query(f"SELECT id, title, status FROM BacklogItem WHERE id = '{item_id}'")
    assert len(rows) == 1
    assert rows[0]["title"] == "Persisted item"
    assert rows[0]["status"] == "open"


def test_record_backlog_item_creates_edge_when_plan_exists(store_with_plan):
    from agentscaffold.graph.backlog import record_backlog_item

    result = record_backlog_item(store_with_plan, plan_number=151, title="Item with plan link")
    item_id = result["id"]

    rows = store_with_plan.query(f"SELECT src, dst FROM BACKLOG_ITEM_OF WHERE src = '{item_id}'")
    assert len(rows) == 1
    assert rows[0]["dst"] == "plan::151"


def test_record_backlog_item_no_edge_when_plan_missing(store):
    from agentscaffold.graph.backlog import record_backlog_item

    # Plan 999 does not exist
    result = record_backlog_item(store, plan_number=999, title="Orphan item")
    item_id = result["id"]

    rows = store.query(f"SELECT src FROM BACKLOG_ITEM_OF WHERE src = '{item_id}'")
    assert rows == []


def test_record_backlog_item_deterministic_id(store):
    from agentscaffold.graph.backlog import record_backlog_item

    r1 = record_backlog_item(store, plan_number=151, title="Same title")
    # Insert again — should get the same ID (create_node is idempotent)
    r2 = record_backlog_item(store, plan_number=151, title="Same title")
    assert r1["id"] == r2["id"]


# ---------------------------------------------------------------------------
# record_backlog_items_batch
# ---------------------------------------------------------------------------


def test_record_backlog_items_batch_empty(store):
    from agentscaffold.graph.backlog import record_backlog_items_batch

    result = record_backlog_items_batch(store, plan_number=151, items=[])
    assert result["ids"] == []
    assert result["count"] == 0


def test_record_backlog_items_batch_single(store):
    from agentscaffold.graph.backlog import record_backlog_items_batch

    result = record_backlog_items_batch(
        store, plan_number=151, items=[{"title": "Solo batch item", "priority": "P2"}]
    )
    assert result["count"] == 1
    assert len(result["ids"]) == 1


def test_record_backlog_items_batch_multiple(store):
    from agentscaffold.graph.backlog import record_backlog_items_batch

    items = [
        {"title": "Item A", "priority": "P1"},
        {"title": "Item B", "priority": "P2"},
        {"title": "Item C", "priority": "P3", "effort": "Small (2h)", "source": "EX-8"},
    ]
    result = record_backlog_items_batch(store, plan_number=151, items=items)
    assert result["count"] == 3
    assert len(result["ids"]) == 3
    # All IDs are unique
    assert len(set(result["ids"])) == 3


def test_record_backlog_items_batch_all_persisted(store):
    from agentscaffold.graph.backlog import record_backlog_items_batch

    items = [{"title": f"Batch item {i}"} for i in range(5)]
    record_backlog_items_batch(store, plan_number=151, items=items)

    rows = store.query("SELECT id FROM BacklogItem WHERE planNumber = 151")
    assert len(rows) == 5


def test_record_backlog_items_batch_creates_edges(store_with_plan):
    from agentscaffold.graph.backlog import record_backlog_items_batch

    items = [{"title": "Edge item A"}, {"title": "Edge item B"}]
    result = record_backlog_items_batch(store_with_plan, plan_number=151, items=items)

    for item_id in result["ids"]:
        rows = store_with_plan.query(f"SELECT dst FROM BACKLOG_ITEM_OF WHERE src = '{item_id}'")
        assert len(rows) == 1
        assert rows[0]["dst"] == "plan::151"


# ---------------------------------------------------------------------------
# resolve_backlog_item
# ---------------------------------------------------------------------------


def test_resolve_backlog_item_sets_archived(store):
    from agentscaffold.graph.backlog import record_backlog_item, resolve_backlog_item

    created = record_backlog_item(store, plan_number=151, title="Item to resolve")
    item_id = created["id"]

    resolved = resolve_backlog_item(store, item_id, resolution="Fixed in Plan 151")
    assert resolved["status"] == "archived"
    assert resolved["id"] == item_id

    rows = store.query(
        f"SELECT status, archivedAt, resolution FROM BacklogItem WHERE id = '{item_id}'"
    )
    assert rows[0]["status"] == "archived"
    assert rows[0]["archivedAt"] != ""
    assert rows[0]["resolution"] == "Fixed in Plan 151"


def test_resolve_backlog_item_elapsed_ms(store):
    from agentscaffold.graph.backlog import record_backlog_item, resolve_backlog_item

    created = record_backlog_item(store, plan_number=151, title="Timing item")
    result = resolve_backlog_item(store, created["id"])
    assert result["elapsed_ms"] >= 0


# ---------------------------------------------------------------------------
# get_open_backlog_items
# ---------------------------------------------------------------------------


def test_get_open_backlog_items_excludes_archived(store):
    from agentscaffold.graph.backlog import (
        get_open_backlog_items,
        record_backlog_item,
        resolve_backlog_item,
    )

    r1 = record_backlog_item(store, plan_number=151, title="Open item")
    r2 = record_backlog_item(store, plan_number=151, title="Archived item")
    resolve_backlog_item(store, r2["id"])

    open_items = get_open_backlog_items(store)
    open_ids = [i.get("bi.id") for i in open_items]
    assert r1["id"] in open_ids
    assert r2["id"] not in open_ids


def test_get_open_backlog_items_filters_by_plan(store):
    from agentscaffold.graph.backlog import get_open_backlog_items, record_backlog_item

    record_backlog_item(store, plan_number=151, title="Plan 151 item")
    record_backlog_item(store, plan_number=200, title="Plan 200 item")

    items_151 = get_open_backlog_items(store, plan_number=151)
    assert all(i.get("bi.planNumber") == 151 for i in items_151)
    assert len(items_151) == 1


def test_get_open_backlog_items_respects_limit(store):
    from agentscaffold.graph.backlog import get_open_backlog_items, record_backlog_items_batch

    items = [{"title": f"Item {i}"} for i in range(10)]
    record_backlog_items_batch(store, plan_number=151, items=items)

    result = get_open_backlog_items(store, limit=3)
    assert len(result) <= 3


def test_get_open_backlog_items_empty(store):
    from agentscaffold.graph.backlog import get_open_backlog_items

    result = get_open_backlog_items(store)
    assert result == []


# ---------------------------------------------------------------------------
# get_backlog_items_for_plan
# ---------------------------------------------------------------------------


def test_get_backlog_items_for_plan_all_statuses(store):
    from agentscaffold.graph.backlog import (
        get_backlog_items_for_plan,
        record_backlog_item,
        resolve_backlog_item,
    )

    r_open = record_backlog_item(store, plan_number=151, title="Open item")
    r_arch = record_backlog_item(store, plan_number=151, title="Archived item")
    resolve_backlog_item(store, r_arch["id"])

    # Without archived
    items = get_backlog_items_for_plan(store, 151)
    ids = [i.get("bi.id") for i in items]
    assert r_open["id"] in ids
    assert r_arch["id"] not in ids

    # With archived
    items_all = get_backlog_items_for_plan(store, 151, include_archived=True)
    ids_all = [i.get("bi.id") for i in items_all]
    assert r_open["id"] in ids_all
    assert r_arch["id"] in ids_all


def test_get_backlog_items_for_plan_empty(store):
    from agentscaffold.graph.backlog import get_backlog_items_for_plan

    result = get_backlog_items_for_plan(store, 999)
    assert result == []


# ---------------------------------------------------------------------------
# MCP tool dispatch (server handlers)
# ---------------------------------------------------------------------------


def test_mcp_record_backlog_item_single(store):
    from agentscaffold.mcp.server import _tool_record_backlog_item

    meta = {}
    result = _tool_record_backlog_item(
        store,
        {"plan_number": 151, "title": "MCP single item", "priority": "P2"},
        meta,
    )
    assert "id" in result
    assert result["status"] == "open"
    assert result["meta"] == meta


def test_mcp_record_backlog_item_batch(store):
    from agentscaffold.mcp.server import _tool_record_backlog_item

    items = [
        {"title": "Batch A", "priority": "P1"},
        {"title": "Batch B", "priority": "P2"},
    ]
    result = _tool_record_backlog_item(store, {"plan_number": 151, "items": items}, {})
    assert result["count"] == 2
    assert len(result["ids"]) == 2


def test_mcp_record_backlog_item_missing_plan(store):
    from agentscaffold.mcp.server import _tool_record_backlog_item

    result = _tool_record_backlog_item(store, {"title": "No plan"}, {})
    assert "error" in result


def test_mcp_record_backlog_item_missing_title(store):
    from agentscaffold.mcp.server import _tool_record_backlog_item

    result = _tool_record_backlog_item(store, {"plan_number": 151}, {})
    assert "error" in result


def test_mcp_resolve_backlog_item(store):
    from agentscaffold.graph.backlog import record_backlog_item
    from agentscaffold.mcp.server import _tool_resolve_backlog_item

    created = record_backlog_item(store, plan_number=151, title="Item to MCP-resolve")
    result = _tool_resolve_backlog_item(store, {"item_id": created["id"], "resolution": "Done"}, {})
    assert result["status"] == "archived"


def test_mcp_resolve_backlog_item_missing_id(store):
    from agentscaffold.mcp.server import _tool_resolve_backlog_item

    result = _tool_resolve_backlog_item(store, {}, {})
    assert "error" in result


def test_resolve_backlog_item_bogus_id_is_not_found(store):
    from agentscaffold.graph.backlog import resolve_backlog_item

    result = resolve_backlog_item(store, "TOTALLY-BOGUS-ID-THAT-CANNOT-EXIST")
    assert result["status"] == "not_found"
    assert "archived_at" not in result
    rows = store.query(
        "SELECT count(*) AS c FROM BacklogItem WHERE id = 'TOTALLY-BOGUS-ID-THAT-CANNOT-EXIST'"
    )
    assert rows[0]["c"] == 0


def test_mcp_resolve_backlog_item_bogus_id_has_error_code(store):
    from agentscaffold.mcp.server import _tool_resolve_backlog_item

    result = _tool_resolve_backlog_item(
        store, {"item_id": "TOTALLY-BOGUS-ID-THAT-CANNOT-EXIST"}, {}
    )
    assert result["status"] == "not_found"
    assert result["error_code"] == "not_found"
    assert "not found" in str(result["error"]).lower()


def test_resolve_backlog_item_human_id_colon_prefix(store):
    from agentscaffold.graph.backlog import record_backlog_item, resolve_backlog_item

    created = record_backlog_item(store, plan_number=151, title="DQ-043: example item")
    result = resolve_backlog_item(store, "DQ-043", resolution="done via human id")
    assert result["status"] == "archived"
    assert result["id"] == created["id"]
    rows = store.query(f"SELECT status, resolution FROM BacklogItem WHERE id = '{created['id']}'")
    assert rows[0]["status"] == "archived"
    assert rows[0]["resolution"] == "done via human id"


def test_resolve_backlog_item_hyphen_gated_space_prefix(store):
    from agentscaffold.graph.backlog import record_backlog_item, resolve_backlog_item

    created = record_backlog_item(store, plan_number=151, title="B-249-1 Fix the lock")
    result = resolve_backlog_item(store, "B-249-1")
    assert result["status"] == "archived"
    assert result["id"] == created["id"]


def test_resolve_backlog_item_space_prefix_refused_without_hyphen(store):
    from agentscaffold.graph.backlog import record_backlog_item, resolve_backlog_item

    created = record_backlog_item(store, plan_number=151, title="Plan 255 follow-up")
    result = resolve_backlog_item(store, "Plan")
    assert result["status"] == "not_found"
    rows = store.query(f"SELECT status FROM BacklogItem WHERE id = '{created['id']}'")
    assert rows[0]["status"] == "open"


def test_resolve_backlog_item_ambiguous_title_prefix(store):
    from agentscaffold.graph.backlog import record_backlog_item, resolve_backlog_item

    a = record_backlog_item(store, plan_number=151, title="DQ-043: first")
    b = record_backlog_item(store, plan_number=151, title="DQ-043: second")
    result = resolve_backlog_item(store, "DQ-043")
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) >= 2
    for item_id in (a["id"], b["id"]):
        rows = store.query(f"SELECT status FROM BacklogItem WHERE id = '{item_id}'")
        assert rows[0]["status"] == "open"


def test_resolve_backlog_item_exact_id_wins_over_title(store):
    from agentscaffold.graph.backlog import record_backlog_item, resolve_backlog_item

    created = record_backlog_item(store, plan_number=151, title="exact-id-item")
    # A second row whose title equals the first row's bi:: id would be a title
    # match, but exact id must still win.
    record_backlog_item(store, plan_number=151, title=created["id"])
    result = resolve_backlog_item(store, created["id"])
    assert result["status"] == "archived"
    assert result["id"] == created["id"]


def test_resolve_backlog_item_qualified_id_forms(store):
    from agentscaffold.graph.backlog import resolve_backlog_item

    store.create_node(
        "BacklogItem",
        {
            "id": "alpha::bi::cafebabeface",
            "planNumber": 1,
            "title": "prefixed item",
            "priority": "P3",
            "effort": "",
            "status": "open",
            "source": "",
            "createdAt": "",
            "archivedAt": "",
            "resolution": "",
            "project": "alpha",
        },
    )
    result = resolve_backlog_item(store, "bi::cafebabeface", project="alpha")
    assert result["status"] == "archived"
    assert result["id"] == "alpha::bi::cafebabeface"


def test_resolve_backlog_item_project_filter_miss(store):
    from agentscaffold.graph.backlog import record_backlog_item, resolve_backlog_item

    created = record_backlog_item(
        store, plan_number=151, title="other-project item", project="beta"
    )
    result = resolve_backlog_item(store, created["id"], project="alpha")
    assert result["status"] == "not_found"
    rows = store.query(f"SELECT status FROM BacklogItem WHERE id = '{created['id']}'")
    assert rows[0]["status"] == "open"


def test_resolve_backlog_item_strips_whitespace(store):
    from agentscaffold.graph.backlog import record_backlog_item, resolve_backlog_item

    created = record_backlog_item(store, plan_number=151, title="DQ-044: spaced")
    result = resolve_backlog_item(store, "  DQ-044  ")
    assert result["status"] == "archived"
    assert result["id"] == created["id"]
