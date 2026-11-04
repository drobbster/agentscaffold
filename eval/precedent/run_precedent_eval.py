"""Precedent retrieval study: labelling sheet and scoring (Plan 281).

``sheet`` selects completed plans from each registered project (a slice), runs
every arm of the shipped ``precedent_for`` for each plan, and writes the pooled
top candidates to ``labels.yaml`` for a human to judge, plus the per-arm
rankings to ``rankings.json``. ``score`` reads both back and reports recall and
precision at 5 per arm and slice on the holdout plans, with the decision rule
for the semantic default.

Only items from plans numbered before the plan under study are candidates, so
a plan is never shown precedent written after it. ADRs reached by semantic
search carry no plan number and are kept.

Usage::

    python -m eval.precedent.run_precedent_eval sheet \\
        --project agentscaffold-governance --project rebellion-trading-system \\
        --out <dir>
    python -m eval.precedent.run_precedent_eval score --out <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agentscaffold.graph.query_compat import sql_escape
from agentscaffold.review.precedent import (
    MATCH_ORDER,
    PrecedentItem,
    PrecedentSource,
    precedent_for,
)

LABELS_FILE = "labels.yaml"
RANKINGS_FILE = "rankings.json"
RESULTS_FILE = "results.json"

K = 5
POOL_DEPTH = 10
RECALL_LIFT = 0.15
MIN_PRECISION = 0.5

NON_SEMANTIC = ("links", "paths", "overlap")
SEMANTIC = ("semantic", "semantic_rerank")


@dataclass(frozen=True)
class Arm:
    name: str
    match_kinds: tuple[str, ...]
    semantic: bool = False
    rerank: bool = False


ARMS: tuple[Arm, ...] = (
    Arm("links", ("linked",)),
    Arm("paths", ("linked", "path")),
    Arm("overlap", ("linked", "path", "plan_overlap", "adr")),
    Arm("semantic", MATCH_ORDER, semantic=True),
    Arm("semantic_rerank", MATCH_ORDER, semantic=True, rerank=True),
)


@dataclass
class PlanCase:
    number: int
    title: str
    paths: list[str]
    split: str = "tuning"


@dataclass
class Slice:
    project: str
    sources: list[PrecedentSource]
    unavailable: list[dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Plan selection
# ---------------------------------------------------------------------------

_COMPLETE = {"complete", "completed", "done"}


def _rows(store: Any, sql: str) -> list[dict[str, Any]]:
    rows = store.query(sql)
    return [dict(r) for r in rows] if rows else []


def _plan_paths(store: Any, plan_id: str, impact_paths: Any) -> list[str]:
    try:
        stored = json.loads(impact_paths or "[]")
    except (TypeError, ValueError):
        stored = []
    if stored:
        return [str(p) for p in stored]
    rows = _rows(
        store,
        "SELECT f.path AS path FROM PLAN_IMPACTS e JOIN File f ON f.id = e.dst"
        f" WHERE e.src = '{sql_escape(plan_id)}' ORDER BY f.path",
    )
    return [str(r["path"]) for r in rows]


def _holdout_order(project: str, number: int) -> str:
    return hashlib.sha256(f"{project}:{number}".encode()).hexdigest()


def select_plans(
    store: Any,
    project: str,
    *,
    scope_project: str | None,
    count: int = 20,
    holdout: int = 6,
) -> list[PlanCase]:
    """The *count* highest-numbered completed plans that list files; *holdout* held out.

    The holdout is chosen by a hash of project and plan number, so it is fixed
    across runs and not biased toward recent plans.
    """
    scope = f" AND p.project = '{sql_escape(scope_project)}'" if scope_project else ""
    rows = _rows(
        store,
        "SELECT p.id AS id, p.number AS number, p.title AS title, p.status AS status,"
        f" p.impactPaths AS impactPaths FROM Plan p WHERE p.number IS NOT NULL{scope}"
        " ORDER BY p.number DESC",
    )
    cases: list[PlanCase] = []
    for row in rows:
        if str(row.get("status") or "").strip().lower() not in _COMPLETE:
            continue
        paths = _plan_paths(store, str(row["id"]), row.get("impactPaths"))
        if not paths:
            continue
        cases.append(PlanCase(int(row["number"]), str(row.get("title") or ""), paths))
        if len(cases) == count:
            break
    held = sorted(cases, key=lambda c: _holdout_order(project, c.number))[:holdout]
    for case in held:
        case.split = "holdout"
    return sorted(cases, key=lambda c: c.number)


# ---------------------------------------------------------------------------
# Arms and pooling
# ---------------------------------------------------------------------------


def item_key(item: PrecedentItem) -> str:
    return f"{item.project}::{item.id}"


def _earlier(item: PrecedentItem, plan_number: int) -> bool:
    return item.plan_number is None or item.plan_number < plan_number


def run_arms(
    sources: Sequence[PrecedentSource],
    case: PlanCase,
    *,
    arms: Sequence[Arm] = ARMS,
    depth: int = POOL_DEPTH,
) -> dict[str, list[PrecedentItem]]:
    """Top *depth* earlier items per arm for one plan."""
    out: dict[str, list[PrecedentItem]] = {}
    for arm in arms:
        result = precedent_for(
            sources,
            case.paths,
            plan_number=case.number,
            query_text=case.title,
            budget=None,
            semantic=arm.semantic,
            rerank=arm.rerank,
            match_kinds=arm.match_kinds,
        )
        out[arm.name] = [i for i in result.items if _earlier(i, case.number)][:depth]
    return out


def pool(rankings: dict[str, list[PrecedentItem]]) -> list[PrecedentItem]:
    """Every arm's candidates once, in an order that does not reveal which arm found them."""
    seen: dict[str, PrecedentItem] = {}
    for items in rankings.values():
        for item in items:
            seen.setdefault(item_key(item), item)
    return sorted(seen.values(), key=lambda i: hashlib.sha256(item_key(i).encode()).hexdigest())


def _candidate(item: PrecedentItem) -> dict[str, Any]:
    return {
        "key": item_key(item),
        "kind": item.kind,
        "project": item.project,
        "from_plan": item.plan_number,
        "path": item.path or None,
        "text": item.text,
        "relevant": None,
    }


def build_sheet(
    slices: Sequence[Slice], *, count: int, holdout: int, depth: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(labels, rankings)`` documents for *slices*."""
    labels: dict[str, Any] = {
        "instructions": (
            "For each plan, set relevant to yes or no on every candidate: yes when a"
            " reviewer of that plan should have seen it before implementation."
            " Leave nothing blank. Candidates are pooled from every arm and listed"
            " in an order that does not reveal which arm found them."
        ),
        "pool_depth": depth,
        "slices": [],
    }
    rankings: dict[str, Any] = {"k": K, "arms": [a.name for a in ARMS], "slices": {}}
    for sl in slices:
        scope = sl.sources[0].scope_project if sl.sources else None
        cases = select_plans(
            sl.sources[0].store, sl.project, scope_project=scope, count=count, holdout=holdout
        )
        plans_out: list[dict[str, Any]] = []
        ranked_out: dict[str, Any] = {}
        for case in cases:
            ranked = run_arms(sl.sources, case, depth=depth)
            plans_out.append(
                {
                    "plan": case.number,
                    "split": case.split,
                    "title": case.title,
                    "paths": case.paths,
                    "candidates": [_candidate(i) for i in pool(ranked)],
                }
            )
            ranked_out[str(case.number)] = {
                "split": case.split,
                "arms": {name: [item_key(i) for i in items] for name, items in ranked.items()},
            }
        labels["slices"].append(
            {
                "project": sl.project,
                "sources": [s.name for s in sl.sources],
                "sources_unavailable": sl.unavailable,
                "plans": plans_out,
            }
        )
        rankings["slices"][sl.project] = ranked_out
    return labels, rankings


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _judgement(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"yes", "y", "true", "1"}:
        return True
    if text in {"no", "n", "false", "0"}:
        return False
    return None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def score(
    labels: dict[str, Any], rankings: dict[str, Any], *, split: str = "holdout"
) -> dict[str, Any]:
    """Recall and precision at 5 per slice and arm over plans in *split*.

    Recall is relative to the pool: relevant items no arm returned were never
    judged. Precision divides by the items an arm returned, at most 5, since
    the review shows no more than that. A plan with no relevant item is left
    out of recall; an arm that returned nothing is left out of precision.
    """
    k = int(rankings.get("k", K))
    out: dict[str, Any] = {"k": k, "split": split, "slices": {}}
    for sl in labels.get("slices", []):
        project = sl["project"]
        ranked = rankings["slices"].get(project, {})
        per_arm: dict[str, dict[str, list[float]]] = {}
        unjudged = 0
        plans = 0
        for plan in sl.get("plans", []):
            if plan.get("split") != split:
                continue
            plans += 1
            relevant: set[str] = set()
            for cand in plan.get("candidates", []):
                verdict = _judgement(cand.get("relevant"))
                if verdict is None:
                    unjudged += 1
                elif verdict:
                    relevant.add(cand["key"])
            arms = ranked.get(str(plan["plan"]), {}).get("arms", {})
            for name in rankings.get("arms", []):
                top = arms.get(name, [])[:k]
                hits = len(relevant.intersection(top))
                bucket = per_arm.setdefault(name, {"recall": [], "precision": []})
                if relevant:
                    bucket["recall"].append(hits / len(relevant))
                if top:
                    bucket["precision"].append(hits / len(top))
        out["slices"][project] = {
            "plans": plans,
            "unjudged": unjudged,
            "arms": {
                name: {
                    "recall_at_k": _mean(v["recall"]),
                    "precision_at_k": _mean(v["precision"]),
                    "plans_with_relevant": len(v["recall"]),
                    "plans_with_results": len(v["precision"]),
                }
                for name, v in per_arm.items()
            },
        }
    out["decision"] = decide(out["slices"])
    return out


def decide(slices: dict[str, Any]) -> dict[str, Any]:
    """Apply the study's rule for the semantic default.

    On only when a semantic arm lifts holdout recall at 5 by at least 0.15
    over the best non-semantic arm in every slice, with precision at 5 of at
    least 0.5. Passing in some slices only leaves it off and names them.
    """
    passing: dict[str, list[str]] = {arm: [] for arm in SEMANTIC}
    detail: dict[str, Any] = {}
    for project, data in slices.items():
        arms = data["arms"]
        best = max((arms.get(a, {}).get("recall_at_k") or 0.0 for a in NON_SEMANTIC), default=0.0)
        detail[project] = {"best_non_semantic_recall": best}
        for arm in SEMANTIC:
            stats = arms.get(arm, {})
            recall = stats.get("recall_at_k") or 0.0
            precision = stats.get("precision_at_k") or 0.0
            lift = round(recall - best, 4)
            ok = lift >= RECALL_LIFT and precision >= MIN_PRECISION
            detail[project][arm] = {"lift": lift, "precision_at_k": precision, "passes": ok}
            if ok:
                passing[arm].append(project)
    every = [arm for arm, hits in passing.items() if slices and len(hits) == len(slices)]
    some = {arm: hits for arm, hits in passing.items() if hits and arm not in every}
    return {
        "semantic_default": bool(every),
        "rerank": bool(every) and every[0] == "semantic_rerank" and "semantic" not in every,
        "passes_everywhere": every,
        "passes_in_some_slices": some,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Opening slices from registered projects
# ---------------------------------------------------------------------------


def _scope_for(store: Any, project: str) -> str | None:
    rows = _rows(store, f"SELECT count(*) AS n FROM Plan WHERE project = '{sql_escape(project)}'")
    return project if rows and int(rows[0]["n"]) > 0 else None


def require_current_schema(store: Any, project: str) -> None:
    """Refuse a graph indexed before Plan 281: every arm would come back empty."""
    try:
        store.query("SELECT impactPaths FROM Plan LIMIT 1")
        store.query("SELECT paths FROM ReviewFinding LIMIT 1")
        store.query("SELECT paths FROM Learning LIMIT 1")
    except Exception as exc:  # noqa: BLE001 - any failure here means a stale graph
        raise SystemExit(
            f"graph for {project!r} predates Plan 281 (no stored paths); reindex it first"
        ) from exc


@contextmanager
def open_slices(projects: Sequence[str]) -> Iterator[list[Slice]]:
    """Each registered project's graph plus its configured precedent sources, read-only."""
    from agentscaffold.config import find_config, load_config
    from agentscaffold.review.file_impact_resolve import open_registered_project_graph
    from agentscaffold.workspace_registry import find_registered_project_by_name

    with ExitStack() as stack:
        slices: list[Slice] = []
        for name in projects:
            hit = find_registered_project_by_name(name)
            store, reason = open_registered_project_graph(name)
            if hit is None or store is None:
                raise SystemExit(f"cannot open project {name!r}: {reason or 'not_registered'}")
            stack.callback(store.close)
            require_current_schema(store, name)
            cfg = load_config(find_config(start=Path(hit.project_root)))
            sl = Slice(name, [PrecedentSource(name, store, _scope_for(store, name))])
            extra = [getattr(cfg, "implementation_project", None), *cfg.precedent.sources]
            for other_name in dict.fromkeys(n for n in extra if n and n != name):
                other, why = open_registered_project_graph(other_name)
                if other is None:
                    sl.unavailable.append({"project": other_name, "reason": why or ""})
                    continue
                stack.callback(other.close)
                sl.sources.append(PrecedentSource(other_name, other, _scope_for(other, other_name)))
            slices.append(sl)
        yield slices


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def write_sheet(
    out_dir: Path,
    projects: Sequence[str],
    *,
    count: int = 20,
    holdout: int = 6,
    depth: int = POOL_DEPTH,
    opener: Callable[[Sequence[str]], Any] = open_slices,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    labels_path = out_dir / LABELS_FILE
    if labels_path.exists():
        raise SystemExit(f"{labels_path} exists; refusing to overwrite labels")
    with opener(projects) as slices:
        labels, rankings = build_sheet(slices, count=count, holdout=holdout, depth=depth)
    labels_path.write_text(yaml.safe_dump(labels, sort_keys=False, width=100), encoding="utf-8")
    (out_dir / RANKINGS_FILE).write_text(json.dumps(rankings, indent=2) + "\n", encoding="utf-8")
    return labels_path


def write_scores(out_dir: Path, *, split: str = "holdout") -> dict[str, Any]:
    labels = yaml.safe_load((out_dir / LABELS_FILE).read_text(encoding="utf-8"))
    rankings = json.loads((out_dir / RANKINGS_FILE).read_text(encoding="utf-8"))
    result = score(labels, rankings, split=split)
    name = RESULTS_FILE if split == "holdout" else f"results_{split}.json"
    (out_dir / name).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_precedent_eval", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sheet = sub.add_parser("sheet", help="write the pooled labelling sheet")
    sheet.add_argument("--project", action="append", required=True, help="registered project")
    sheet.add_argument("--out", type=Path, required=True)
    sheet.add_argument("--plans", type=int, default=20)
    sheet.add_argument("--holdout", type=int, default=6)
    sheet.add_argument("--depth", type=int, default=POOL_DEPTH)
    sc = sub.add_parser("score", help="score labelled arms")
    sc.add_argument("--out", type=Path, required=True)
    sc.add_argument("--split", choices=("holdout", "tuning"), default="holdout")
    args = parser.parse_args(argv)

    if args.command == "sheet":
        path = write_sheet(
            args.out, args.project, count=args.plans, holdout=args.holdout, depth=args.depth
        )
        print(f"wrote {path}")
        return 0
    result = write_scores(args.out, split=args.split)
    print(json.dumps(result["decision"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
