"""Precedent: earlier findings, learnings and ADRs about the files a plan touches.

Plan 281. The pre-implementation review, ``scaffold_prepare_implementation``
and ``scaffold_impact`` all ask the same question -- what does the governance
history already say about these files? -- and answer it here.

Match kinds, in rank order:

``linked``
    A graph edge from the item to the file (``FINDING_ABOUT_FILE``,
    ``LEARNING_RELATES_TO_FILE``).
``path``
    The item's stored ``paths`` column names the file; rows recorded before
    that column existed are matched on their text instead.
``plan_overlap``
    The item came from an earlier plan whose File Impact Map lists the file.
``adr``
    An ADR governing such a plan.
``semantic``
    Embedding similarity to the query text; only when asked for.

Within a kind, items recorded by an agent or human come before automated
review output, then higher severity, then the more recent plan. Finding status
is not used: whether a finding was marked resolved is not reliable enough to
rank on. Statistic categories (counts, not judgments) and the plan's own items
are never returned. Every read is read-only.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentscaffold.graph.query_compat import sql_escape
from agentscaffold.repo_paths import path_spellings

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend

logger = logging.getLogger(__name__)

MATCH_ORDER: tuple[str, ...] = ("linked", "path", "plan_overlap", "adr", "semantic")
STRUCTURAL_MATCHES: tuple[str, ...] = ("linked", "path", "adr")
DEFAULT_STATISTIC_CATEGORIES: frozenset[str] = frozenset(
    {"HISTORY", "VOLATILITY", "HOT_FILE", "COMPLEXITY"}
)
#: Review types written by the review engine rather than an agent or human.
AUTOMATED_REVIEW_TYPES: frozenset[str] = frozenset({"pre_review", "plan_appendix"})
DEFAULT_AUTOMATED_SKIP_CATEGORIES: frozenset[str] = frozenset(
    {"DEPENDENCY", "CONSUMER_AUDIT", "TEST_COVERAGE"}
)

_KIND_ORDER = {"finding": 0, "learning": 1, "adr": 2}
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_MAX_TEXT = 240
#: Bound on rows scanned by the text match for findings recorded before ``paths``.
_LEGACY_SCAN_LIMIT = 2000
_COMPACT_KEYS = ("id", "kind", "match", "plan", "project", "text")


@dataclass(frozen=True)
class PrecedentItem:
    """One earlier finding, learning or ADR and how it matched."""

    kind: str
    id: str
    match: str
    path: str
    plan_number: int | None
    text: str
    project: str = ""
    severity: str = ""
    category: str = ""
    review_type: str = ""
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "match": self.match,
            "plan": self.plan_number,
            "project": self.project,
            "text": self.text,
            "path": self.path,
        }
        if self.kind == "finding":
            out["severity"] = self.severity
            out["category"] = self.category
            out["review_type"] = self.review_type
        if self.score is not None:
            out["score"] = self.score
        return out

    def to_compact(self) -> dict[str, Any]:
        full = self.to_dict()
        return {key: full[key] for key in _COMPACT_KEYS}


@dataclass
class PrecedentSource:
    """A graph to read precedent from, named by its registered project."""

    name: str
    store: GraphBackend
    #: Restricts reads to one project of a shared multi-project graph.
    scope_project: str | None = None


@dataclass
class PrecedentResult:
    items: list[PrecedentItem]
    total: int
    sources: list[str] = field(default_factory=list)
    sources_unavailable: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total": self.total,
            "sources": list(self.sources),
            "sources_unavailable": list(self.sources_unavailable),
        }


@dataclass
class OpenedSources:
    sources: list[PrecedentSource]
    unavailable: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def precedent_for(
    sources: Sequence[PrecedentSource],
    paths: Sequence[str],
    *,
    plan_number: int | None = None,
    query_text: str = "",
    budget: int | None = 5,
    semantic: bool = False,
    rerank: bool = False,
    match_kinds: Collection[str] = MATCH_ORDER,
    statistic_categories: Collection[str] = DEFAULT_STATISTIC_CATEGORIES,
    automated_skip_categories: Collection[str] = DEFAULT_AUTOMATED_SKIP_CATEGORIES,
) -> PrecedentResult:
    """Rank earlier items about *paths* across *sources*; at most *budget* (None: all).

    *rerank* applies a cross-encoder to the semantic layer only. Findings in
    *statistic_categories*, and automated findings in *automated_skip_categories*,
    are never returned. An ``@repo/`` path also matches its VCS-relative
    spelling, which is how review text names files outside the project folder.
    """
    wanted = [s for p in dict.fromkeys(paths) if p for s in path_spellings(p)]
    wanted = list(dict.fromkeys(wanted))
    if not wanted:
        return PrecedentResult(items=[], total=0, sources=[s.name for s in sources])
    skip = _Skip(
        stats=frozenset(c.upper() for c in statistic_categories),
        automated=frozenset(c.upper() for c in automated_skip_categories),
    )
    kinds = set(match_kinds)
    if not semantic:
        kinds.discard("semantic")

    candidates: list[PrecedentItem] = []
    for source in sources:
        candidates.extend(
            _from_source(source, wanted, plan_number, kinds, skip, query_text, rerank)
        )

    ranked = sorted(candidates, key=_rank_key)
    seen: set[tuple[str, str]] = set()
    unique: list[PrecedentItem] = []
    for item in ranked:
        key = (item.project, item.id)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    items = unique if budget is None else unique[: max(budget, 0)]
    return PrecedentResult(items=items, total=len(unique), sources=[s.name for s in sources])


def _rank_key(item: PrecedentItem) -> tuple[Any, ...]:
    automated = 1 if item.review_type in AUTOMATED_REVIEW_TYPES else 0
    severity = _SEVERITY_RANK.get(item.severity.lower(), _SEVERITY_RANK["medium"])
    # Semantic hits order by similarity first; structural matches carry no score.
    similarity = -(item.score or 0.0) if item.match == "semantic" else 0.0
    return (
        MATCH_ORDER.index(item.match),
        similarity,
        automated,
        severity,
        -(item.plan_number or 0),
        _KIND_ORDER[item.kind],
        item.project,
        item.id,
    )


@dataclass(frozen=True)
class _Skip:
    stats: frozenset[str]
    automated: frozenset[str]

    def excludes(self, row: dict[str, Any]) -> bool:
        category = str(row.get("category") or "").upper()
        if category in self.stats:
            return True
        automated = str(row.get("reviewType") or "").lower() in AUTOMATED_REVIEW_TYPES
        return automated and category in self.automated


def _from_source(
    source: PrecedentSource,
    paths: list[str],
    plan_number: int | None,
    kinds: set[str],
    skip: _Skip,
    query_text: str,
    rerank: bool = False,
) -> list[PrecedentItem]:
    out: list[PrecedentItem] = []

    def keep_finding(row: dict[str, Any]) -> bool:
        if skip.excludes(row):
            return False
        return plan_number is None or _as_int(row.get("planNumber")) != plan_number

    def keep_learning(row: dict[str, Any]) -> bool:
        return plan_number is None or _as_int(row.get("planNumber")) != plan_number

    if "linked" in kinds:
        for row in _linked_findings(source, paths):
            if keep_finding(row):
                out.append(_finding_item(source, row, "linked", row["matched"]))
        for row in _linked_learnings(source, paths):
            if keep_learning(row):
                out.append(_learning_item(source, row, "linked", row["matched"]))

    if "path" in kinds:
        for row in _path_findings(source, paths):
            if keep_finding(row):
                out.append(_finding_item(source, row, "path", row["matched"]))
        for row in _path_learnings(source, paths):
            if keep_learning(row):
                out.append(_learning_item(source, row, "path", row["matched"]))

    if kinds & {"plan_overlap", "adr"}:
        overlap = _overlap_plans(source, paths, plan_number)
        if overlap and "plan_overlap" in kinds:
            for row in _plan_findings(source, list(overlap)):
                if keep_finding(row):
                    matched = overlap[_as_int(row.get("planNumber")) or 0]
                    out.append(_finding_item(source, row, "plan_overlap", matched))
            for row in _plan_learnings(source, list(overlap)):
                if keep_learning(row):
                    matched = overlap[_as_int(row.get("planNumber")) or 0]
                    out.append(_learning_item(source, row, "plan_overlap", matched))
        if overlap and "adr" in kinds:
            for row in _governing_adrs(source, list(overlap)):
                plan = _as_int(row.get("plan"))
                out.append(
                    PrecedentItem(
                        kind="adr",
                        id=f"adr::{row['number']}",
                        match="adr",
                        path=overlap.get(plan or 0, ""),
                        plan_number=plan,
                        text=_one_line(f"ADR-{row['number']}: {row.get('title') or ''}"),
                        project=source.name,
                    )
                )

    if "semantic" in kinds and query_text.strip():
        out.extend(_semantic(source, query_text, paths, plan_number, skip, rerank))
    return out


# ---------------------------------------------------------------------------
# Queries (plain SQL over the node and edge tables)
# ---------------------------------------------------------------------------

_FINDING_COLS = (
    "rf.id AS id, rf.reviewType AS reviewType, rf.planNumber AS planNumber,"
    " rf.severity AS severity, rf.category AS category, rf.finding AS finding"
)
_LEARNING_COLS = (
    "lr.id AS id, lr.learningId AS learningId, lr.planNumber AS planNumber,"
    " lr.description AS description"
)


def _scope(source: PrecedentSource, alias: str) -> str:
    if not source.scope_project:
        return ""
    return f" AND {alias}.project = '{sql_escape(source.scope_project)}'"


def _in_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{sql_escape(v)}'" for v in values)


def _query(store: GraphBackend, sql: str) -> list[dict[str, Any]]:
    try:
        return store.query(sql)
    except Exception as exc:  # noqa: BLE001 - an older graph lacks a column or table
        logger.debug("precedent query skipped: %s", exc)
        return []


def _linked_findings(source: PrecedentSource, paths: list[str]) -> list[dict[str, Any]]:
    return _query(
        source.store,
        f"SELECT {_FINDING_COLS}, f.path AS matched"
        " FROM FINDING_ABOUT_FILE e JOIN ReviewFinding rf ON rf.id = e.src"
        " JOIN File f ON f.id = e.dst"
        f" WHERE f.path IN ({_in_list(paths)}){_scope(source, 'rf')}",
    )


def _linked_learnings(source: PrecedentSource, paths: list[str]) -> list[dict[str, Any]]:
    return _query(
        source.store,
        f"SELECT {_LEARNING_COLS}, f.path AS matched"
        " FROM LEARNING_RELATES_TO_FILE e JOIN Learning lr ON lr.id = e.src"
        " JOIN File f ON f.id = e.dst"
        f" WHERE f.path IN ({_in_list(paths)}){_scope(source, 'lr')}",
    )


def _path_predicate(paths: list[str], text_columns: Sequence[str]) -> str:
    stored = " OR ".join(f"strpos(paths, '{sql_escape(json.dumps(p))}') > 0" for p in paths)
    legacy = " OR ".join(
        f"strpos(COALESCE({col}, ''), '{sql_escape(p)}') > 0" for p in paths for col in text_columns
    )
    return f"(({stored}) OR (COALESCE(paths, '[]') = '[]' AND ({legacy})))"


def _first_match(row: dict[str, Any], paths: list[str], text_columns: Sequence[str]) -> str:
    try:
        stored = json.loads(row.get("paths") or "[]")
    except ValueError:
        stored = []
    for p in paths:
        if p in stored:
            return p
    text = " ".join(str(row.get(col) or "") for col in text_columns)
    return next((p for p in paths if p in text), paths[0])


def _path_findings(source: PrecedentSource, paths: list[str]) -> list[dict[str, Any]]:
    cols = ("finding", "evidence")
    rows = _query(
        source.store,
        f"SELECT {_FINDING_COLS}, rf.evidence AS evidence, rf.paths AS paths"
        f" FROM ReviewFinding rf WHERE {_path_predicate(paths, cols)}{_scope(source, 'rf')}"
        f" LIMIT {_LEGACY_SCAN_LIMIT}",
    )
    for row in rows:
        row["matched"] = _first_match(row, paths, cols)
    return rows


def _path_learnings(source: PrecedentSource, paths: list[str]) -> list[dict[str, Any]]:
    cols = ("description", "target")
    rows = _query(
        source.store,
        f"SELECT {_LEARNING_COLS}, lr.target AS target, lr.paths AS paths"
        f" FROM Learning lr WHERE {_path_predicate(paths, cols)}{_scope(source, 'lr')}"
        f" LIMIT {_LEGACY_SCAN_LIMIT}",
    )
    for row in rows:
        row["matched"] = _first_match(row, paths, cols)
    return rows


def _overlap_plans(
    source: PrecedentSource, paths: list[str], plan_number: int | None
) -> dict[int, str]:
    """Earlier plans whose File Impact Map lists one of *paths*: number -> shared path."""
    exclude = f" AND p.number <> {int(plan_number)}" if plan_number is not None else ""
    overlap: dict[int, str] = {}
    for row in _query(
        source.store,
        f"SELECT p.number AS number, p.impactPaths AS impactPaths FROM Plan p"
        f" WHERE COALESCE(p.impactPaths, '[]') <> '[]'{exclude}{_scope(source, 'p')}",
    ):
        try:
            listed = json.loads(row.get("impactPaths") or "[]")
        except ValueError:
            continue
        shared = next((p for p in paths if p in listed), None)
        number = _as_int(row.get("number"))
        if shared and number is not None:
            overlap.setdefault(number, shared)
    # Graphs indexed before impactPaths existed still have PLAN_IMPACTS edges.
    for row in _query(
        source.store,
        "SELECT p.number AS number, f.path AS path FROM PLAN_IMPACTS e"
        " JOIN Plan p ON p.id = e.src JOIN File f ON f.id = e.dst"
        f" WHERE f.path IN ({_in_list(paths)}){exclude}{_scope(source, 'p')}",
    ):
        number = _as_int(row.get("number"))
        if number is not None:
            overlap.setdefault(number, str(row.get("path") or ""))
    return overlap


def _plan_findings(source: PrecedentSource, plans: list[int]) -> list[dict[str, Any]]:
    numbers = ", ".join(str(int(n)) for n in plans)
    return _query(
        source.store,
        f"SELECT {_FINDING_COLS} FROM ReviewFinding rf"
        f" WHERE rf.planNumber IN ({numbers}){_scope(source, 'rf')}",
    )


def _plan_learnings(source: PrecedentSource, plans: list[int]) -> list[dict[str, Any]]:
    numbers = ", ".join(str(int(n)) for n in plans)
    return _query(
        source.store,
        f"SELECT {_LEARNING_COLS} FROM Learning lr"
        f" WHERE lr.planNumber IN ({numbers}){_scope(source, 'lr')}",
    )


def _governing_adrs(source: PrecedentSource, plans: list[int]) -> list[dict[str, Any]]:
    numbers = ", ".join(str(int(n)) for n in plans)
    return _query(
        source.store,
        "SELECT a.number AS number, a.title AS title, p.number AS plan"
        " FROM ADR_GOVERNS e JOIN ADR a ON a.id = e.src JOIN Plan p ON p.id = e.dst"
        f" WHERE p.number IN ({numbers}){_scope(source, 'p')}",
    )


def _semantic(
    source: PrecedentSource,
    query_text: str,
    paths: list[str],
    plan_number: int | None,
    skip: _Skip,
    rerank: bool = False,
) -> list[PrecedentItem]:
    from agentscaffold.graph.search import hybrid_search  # noqa: PLC0415

    try:
        results = hybrid_search(
            source.store,
            query_text,
            mode="semantic",
            top_k=20,
            tables=["ReviewFinding", "Learning", "ADR"],
            project=source.scope_project,
            rerank=rerank,
        )
    except Exception as exc:  # noqa: BLE001 - no embeddings or model: no semantic layer
        logger.debug("semantic precedent unavailable: %s", exc)
        return []

    out: list[PrecedentItem] = []
    for hit in results:
        row = _row_for(source, hit.node_type, hit.node_id)
        if row is None:
            continue
        if hit.node_type == "ReviewFinding":
            if skip.excludes(row):
                continue
            if plan_number is not None and _as_int(row.get("planNumber")) == plan_number:
                continue
            item = _finding_item(source, row, "semantic", "")
        elif hit.node_type == "Learning":
            if plan_number is not None and _as_int(row.get("planNumber")) == plan_number:
                continue
            item = _learning_item(source, row, "semantic", "")
        else:
            item = PrecedentItem(
                kind="adr",
                id=f"adr::{row['number']}",
                match="semantic",
                path="",
                plan_number=None,
                text=_one_line(f"ADR-{row['number']}: {row.get('title') or ''}"),
                project=source.name,
            )
        out.append(_with_score(item, hit.score))
    return out


def _row_for(source: PrecedentSource, table: str, node_id: str) -> dict[str, Any] | None:
    cols = {
        "ReviewFinding": _FINDING_COLS + " FROM ReviewFinding rf WHERE rf.id",
        "Learning": _LEARNING_COLS + " FROM Learning lr WHERE lr.id",
        "ADR": "a.number AS number, a.title AS title FROM ADR a WHERE a.id",
    }.get(table)
    if cols is None:
        return None
    rows = _query(source.store, f"SELECT {cols} = '{sql_escape(node_id)}' LIMIT 1")
    return rows[0] if rows else None


def _with_score(item: PrecedentItem, score: float) -> PrecedentItem:
    from dataclasses import replace  # noqa: PLC0415

    return replace(item, score=round(float(score), 4))


# ---------------------------------------------------------------------------
# Item construction
# ---------------------------------------------------------------------------


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _one_line(text: str) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= _MAX_TEXT else flat[: _MAX_TEXT - 3].rstrip() + "..."


def _finding_item(
    source: PrecedentSource, row: dict[str, Any], match: str, path: str
) -> PrecedentItem:
    return PrecedentItem(
        kind="finding",
        id=str(row["id"]),
        match=match,
        path=path,
        plan_number=_as_int(row.get("planNumber")),
        text=_one_line(row.get("finding") or ""),
        project=source.name,
        severity=str(row.get("severity") or ""),
        category=str(row.get("category") or ""),
        review_type=str(row.get("reviewType") or ""),
    )


def _learning_item(
    source: PrecedentSource, row: dict[str, Any], match: str, path: str
) -> PrecedentItem:
    return PrecedentItem(
        kind="learning",
        id=str(row["id"]),
        match=match,
        path=path,
        plan_number=_as_int(row.get("planNumber")),
        text=_one_line(row.get("description") or ""),
        project=source.name,
    )


# ---------------------------------------------------------------------------
# Sources and the configured entry point
# ---------------------------------------------------------------------------


def _scope_project_for(store: GraphBackend) -> str | None:
    from agentscaffold.review.queries import _resolve_scope  # noqa: PLC0415

    try:
        scope = _resolve_scope(None, False)
    except Exception:  # noqa: BLE001 - no workspace: a lone graph needs no scope
        return None
    return None if getattr(scope, "is_noop", True) else str(scope.project)


@contextmanager
def open_precedent_sources(
    store: GraphBackend,
    *,
    root: Path,
    config: Any = None,
) -> Iterator[OpenedSources]:
    """The current project's graph plus its named sources, opened read-only.

    Named sources are ``implementation_project`` and ``precedent.sources``.
    One that cannot be opened is reported in ``unavailable``, never raised.
    """
    from agentscaffold.config import find_config, load_config  # noqa: PLC0415
    from agentscaffold.review.file_impact_resolve import (  # noqa: PLC0415
        current_project_name,
        open_registered_project_graph,
    )

    cfg = config if config is not None else load_config(find_config(start=root))
    current = current_project_name(root, cfg)
    sources = [PrecedentSource(current, store, _scope_project_for(store))]
    unavailable: list[dict[str, str]] = []
    opened: list[Any] = []

    names = [getattr(cfg, "implementation_project", None), *cfg.precedent.sources]
    for name in dict.fromkeys(n for n in names if n and n != current):
        other, reason = open_registered_project_graph(name)
        if other is None:
            unavailable.append({"project": name, "reason": reason or "graph_unavailable"})
            continue
        opened.append(other)
        sources.append(PrecedentSource(name, other))
    try:
        yield OpenedSources(sources=sources, unavailable=unavailable)
    finally:
        for other in opened:
            try:
                other.close()
            except Exception:  # noqa: BLE001
                pass


def precedent_for_paths(
    store: GraphBackend,
    paths: Sequence[str],
    *,
    root: Path,
    config: Any = None,
    plan_number: int | None = None,
    query_text: str = "",
    budget: int | None = 5,
    match_kinds: Collection[str] = MATCH_ORDER,
) -> PrecedentResult | None:
    """Precedent with the project's ``precedent`` settings; None when disabled."""
    from agentscaffold.config import find_config, load_config  # noqa: PLC0415

    cfg = config if config is not None else load_config(find_config(start=root))
    settings = cfg.precedent
    if not settings.enabled:
        return None
    with open_precedent_sources(store, root=root, config=cfg) as opened:
        result = precedent_for(
            opened.sources,
            paths,
            plan_number=plan_number,
            query_text=query_text,
            budget=budget,
            semantic=settings.semantic,
            match_kinds=match_kinds,
            statistic_categories=settings.statistic_categories,
            automated_skip_categories=settings.automated_skip_categories,
        )
        result.sources_unavailable = list(opened.unavailable)
    return result
