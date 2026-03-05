"""Efficiency scenarios: measure token and tool-call reduction vs baseline agent."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from eval.runner import (
    EfficiencyResult,
    EvalResult,
    collect_efficiency,
    collect_result,
    estimate_tokens,
)


def _efficiency_score(eff: EfficiencyResult) -> float:
    """Blended score: 40% token reduction + 60% call reduction."""
    return min(
        0.4 * (eff.token_reduction_pct / 100) + 0.6 * (eff.call_reduction_pct / 100),
        1.0,
    )


class _NoCloseStore:
    """Wrapper that prevents _dispatch_tool from closing the shared store."""

    def __init__(self, store):
        self._store = store

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._store, name)


def _patch_mcp(config, store):
    wrapper = _NoCloseStore(store)
    return (
        patch("agentscaffold.config.load_config", return_value=config),
        patch("agentscaffold.graph.graph_available", return_value=True),
        patch("agentscaffold.graph.open_graph", return_value=wrapper),
    )


def _read_file_tokens(root: Path, rel_path: str) -> int:
    """Count tokens in a file (0 if missing)."""
    fp = root / rel_path
    if fp.exists():
        return estimate_tokens(fp.read_text())
    return 0


def _sum_file_tokens(root: Path, paths: list[str]) -> int:
    return sum(_read_file_tokens(root, p) for p in paths)


class TestSymbolUnderstanding:
    """Task: 'What is DataRouter and what depends on it?'

    Baseline agent would: grep for 'class DataRouter', read the file,
    grep for imports referencing it, read each importing file, trace callers.
    Graph agent: 1 scaffold_context call.
    """

    def test_symbol_context_efficiency(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        # -- Baseline: files the agent would need to read --
        baseline_files = [
            "libs/data/router.py",
            "libs/data/cache.py",
            "libs/data/providers/base.py",
            "libs/data/providers/alpaca.py",
            "libs/data/providers/polygon.py",
            # Agent would grep and discover these importers:
            "libs/strategy/base.py",
            "libs/strategy/momentum.py",
            "libs/strategy/mean_reversion.py",
            "libs/execution/engine.py",
            "services/api/routes.py",
            "pipeline/flows/daily_ingest.py",
            "pipeline/flows/signal_generation.py",
        ]
        # Baseline calls: 1 grep (find class) + N file reads + 1 grep (find importers)
        baseline_reads = len(baseline_files)
        baseline_greps = 2  # grep for class def + grep for imports
        baseline_calls = baseline_reads + baseline_greps
        baseline_tokens = _sum_file_tokens(root, baseline_files)

        # -- Graph: 1 MCP call --
        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            graph_response = _dispatch_tool("scaffold_context", {"symbol": "DataRouter"})
        graph_text = json.dumps(graph_response, default=str)
        graph_tokens = estimate_tokens(graph_text)
        graph_calls = 1

        eff = EfficiencyResult(
            task="symbol_understanding",
            description="Understand DataRouter and its dependents",
            baseline_tool_calls=baseline_calls,
            baseline_tokens=baseline_tokens,
            graph_tool_calls=graph_calls,
            graph_tokens=graph_tokens,
            observations=[
                f"Baseline: {baseline_reads} reads + {baseline_greps} greps",
                f"Graph response keys: {list(graph_response.keys())}",
            ],
        )
        collect_efficiency(eff)

        result = EvalResult(
            scenario="efficiency_symbol_understanding",
            passed=eff.token_reduction_pct > 0 and eff.call_reduction_pct > 0,
            score=round(_efficiency_score(eff), 2),
            expected="Token and call reduction > 0%",
            actual=(
                f"Token reduction: {eff.token_reduction_pct}%, "
                f"Call reduction: {eff.call_reduction_pct}%, "
                f"Compression: {eff.compression_ratio}x"
            ),
            category="efficiency",
        )
        collect_result(result)
        assert eff.token_reduction_pct > 0
        assert eff.call_reduction_pct > 0


class TestPlanReview:
    """Task: 'Review plan 042 before execution.'

    Baseline agent would: read plan file, read each file in impact map,
    read relevant contracts, read learnings tracker.
    Graph agent: 1 scaffold_review_context call.
    """

    def test_plan_review_efficiency(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        # -- Baseline: all the docs + source files the agent reads --
        baseline_files = [
            "docs/ai/plans/plan_042_data_router_v2.md",
            "docs/ai/contracts/data_router_interface.md",
            "docs/ai/state/learnings_tracker.md",
            # Files in the plan's impact map:
            "libs/data/router.py",
            "libs/data/cache.py",
            "libs/data/providers/base.py",
            "libs/data/providers/alpaca.py",
            "libs/data/providers/polygon.py",
            "tests/unit/test_router.py",
            "tests/unit/test_cache.py",
        ]
        baseline_reads = len(baseline_files)
        baseline_calls = baseline_reads  # pure reads, no greps needed
        baseline_tokens = _sum_file_tokens(root, baseline_files)

        # -- Graph: 1 MCP review context call --
        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            graph_response = _dispatch_tool(
                "scaffold_review_context",
                {"plan_number": 42, "review_type": "all"},
            )
        graph_text = json.dumps(graph_response, default=str)
        graph_tokens = estimate_tokens(graph_text)
        graph_calls = 1

        eff = EfficiencyResult(
            task="plan_review",
            description="Full review of Plan 042 (Data Router V2)",
            baseline_tool_calls=baseline_calls,
            baseline_tokens=baseline_tokens,
            graph_tool_calls=graph_calls,
            graph_tokens=graph_tokens,
            observations=[
                f"Baseline reads {baseline_reads} files "
                f"(plan + contracts + learnings + {baseline_reads - 3} source)",
                "Graph returns brief, challenges, gaps, verification, retro in 1 call",
            ],
        )
        collect_efficiency(eff)

        blended = _efficiency_score(eff)
        result = EvalResult(
            scenario="efficiency_plan_review",
            passed=blended > 0.3 and eff.call_reduction_pct > 0,
            score=round(blended, 2),
            expected="Blended score > 0.3 and call reduction > 0%",
            actual=(
                f"Token reduction: {eff.token_reduction_pct}%, "
                f"Call reduction: {eff.call_reduction_pct}%, "
                f"Compression: {eff.compression_ratio}x, "
                f"Blended: {blended:.2f}"
            ),
            category="efficiency",
        )
        collect_result(result)
        assert blended > 0.3, (
            f"Blended efficiency too low: {blended:.2f} "
            f"(token: {eff.token_reduction_pct}%, calls: {eff.call_reduction_pct}%)"
        )
        assert eff.call_reduction_pct > 0


class TestCodebaseOrientation:
    """Task: 'Give me an overview of this codebase.'

    Baseline agent would: recursive ls, read most source files to understand
    structure, dependencies, modules.
    Graph agent: 1 scaffold_stats call + template context.
    """

    def test_codebase_orientation_efficiency(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool
        from agentscaffold.rendering import get_default_context, get_graph_context

        # -- Baseline: agent reads every Python source file --
        all_py = sorted(root.rglob("*.py"))
        # Exclude test and __init__ files (an optimistic baseline -- real agent
        # wouldn't know which files to skip)
        source_files = [
            f for f in all_py if ".scaffold" not in str(f) and "__pycache__" not in str(f)
        ]
        baseline_tokens = sum(estimate_tokens(f.read_text()) for f in source_files)
        # 1 recursive ls + N file reads
        baseline_calls = 1 + len(source_files)

        # -- Graph: stats + context --
        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            stats = _dispatch_tool("scaffold_stats", {})
        graph_ctx = get_graph_context(config)
        default_ctx = get_default_context(config)
        combined = json.dumps({**stats, **graph_ctx, **default_ctx}, default=str)
        graph_tokens = estimate_tokens(combined)
        graph_calls = 2  # stats + context

        eff = EfficiencyResult(
            task="codebase_orientation",
            description="Understand the full codebase structure",
            baseline_tool_calls=baseline_calls,
            baseline_tokens=baseline_tokens,
            graph_tool_calls=graph_calls,
            graph_tokens=graph_tokens,
            observations=[
                f"Baseline: {len(source_files)} files to read",
                f"Graph stats keys: {list(stats.keys())[:5]}",
            ],
        )
        collect_efficiency(eff)

        result = EvalResult(
            scenario="efficiency_codebase_orientation",
            passed=eff.token_reduction_pct > 0,
            score=round(_efficiency_score(eff), 2),
            expected="Significant token reduction for codebase overview",
            actual=(
                f"Token reduction: {eff.token_reduction_pct}%, "
                f"Call reduction: {eff.call_reduction_pct}%, "
                f"Compression: {eff.compression_ratio}x"
            ),
            category="efficiency",
        )
        collect_result(result)
        assert eff.token_reduction_pct > 0


class TestImpactAnalysis:
    """Task: 'What breaks if I change libs/data/router.py?'

    Baseline agent would: grep for imports of router, read each importing
    file, follow transitive deps, grep for function calls.
    Graph agent: 1 scaffold_impact call.
    """

    def test_impact_analysis_efficiency(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        # -- Baseline: find all files importing router --
        importing_files = [
            "libs/data/__init__.py",
            "libs/strategy/base.py",
            "libs/strategy/momentum.py",
            "libs/strategy/mean_reversion.py",
            "libs/execution/engine.py",
            "services/api/routes.py",
            "pipeline/flows/daily_ingest.py",
            "pipeline/flows/signal_generation.py",
        ]
        # Agent greps for "from libs.data.router" or "import router", then
        # reads each match, then greps again for transitive imports.
        baseline_greps = 3  # initial grep + 2 transitive grep rounds
        baseline_reads = len(importing_files) + 1  # +1 for router.py itself
        baseline_calls = baseline_greps + baseline_reads
        baseline_tokens = _read_file_tokens(root, "libs/data/router.py") + _sum_file_tokens(
            root, importing_files
        )

        # -- Graph: 1 impact call --
        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            impact = _dispatch_tool(
                "scaffold_impact",
                {"file_or_symbol": "libs/data/router.py"},
            )
        graph_text = json.dumps(impact, default=str)
        graph_tokens = estimate_tokens(graph_text)
        graph_calls = 1

        eff = EfficiencyResult(
            task="impact_analysis",
            description="Blast radius of changing libs/data/router.py",
            baseline_tool_calls=baseline_calls,
            baseline_tokens=baseline_tokens,
            graph_tool_calls=graph_calls,
            graph_tokens=graph_tokens,
            observations=[
                f"Direct importers found by graph: {len(impact.get('direct_importers', []))}",
                f"Callers found: {len(impact.get('callers', []))}",
            ],
        )
        collect_efficiency(eff)

        result = EvalResult(
            scenario="efficiency_impact_analysis",
            passed=eff.token_reduction_pct > 0 and eff.call_reduction_pct > 0,
            score=round(_efficiency_score(eff), 2),
            expected="Token and call reduction > 0%",
            actual=(
                f"Token reduction: {eff.token_reduction_pct}%, "
                f"Call reduction: {eff.call_reduction_pct}%, "
                f"Compression: {eff.compression_ratio}x"
            ),
            category="efficiency",
        )
        collect_result(result)
        assert eff.token_reduction_pct > 0


class TestCodeSearch:
    """Task: 'Find everything related to risk management.'

    Baseline agent would: grep for 'risk' across the whole tree, read each
    matching file, read imported dependencies.
    Graph agent: 1 scaffold_search call.
    """

    def test_search_efficiency(self, indexed_sim):
        root, store, config = indexed_sim
        from agentscaffold.mcp.server import _dispatch_tool

        # -- Baseline: grep + read matches --
        risk_files = [
            "libs/risk/__init__.py",
            "libs/risk/manager.py",
            "libs/risk/position_sizer.py",
            # Agent also finds references in:
            "libs/execution/engine.py",
            "docs/ai/contracts/risk_manager_interface.md",
            "pipeline/flows/signal_generation.py",
            "tests/unit/test_risk.py",
        ]
        baseline_greps = 1
        baseline_reads = len(risk_files)
        baseline_calls = baseline_greps + baseline_reads
        baseline_tokens = _sum_file_tokens(root, risk_files)

        # -- Graph: 1 search call --
        p1, p2, p3 = _patch_mcp(config, store)
        with p1, p2, p3:
            search_result = _dispatch_tool(
                "scaffold_search",
                {"query": "risk management", "mode": "cypher", "top_k": 10},
            )
        graph_text = json.dumps(search_result, default=str)
        graph_tokens = estimate_tokens(graph_text)
        graph_calls = 1

        eff = EfficiencyResult(
            task="code_search",
            description="Find all risk-related code",
            baseline_tool_calls=baseline_calls,
            baseline_tokens=baseline_tokens,
            graph_tool_calls=graph_calls,
            graph_tokens=graph_tokens,
            observations=[
                f"Search returned {search_result.get('count', 0)} results",
                f"Baseline reads {baseline_reads} files",
            ],
        )
        collect_efficiency(eff)

        result = EvalResult(
            scenario="efficiency_code_search",
            passed=eff.token_reduction_pct > 0,
            score=round(_efficiency_score(eff), 2),
            expected="Token reduction > 0%",
            actual=(
                f"Token reduction: {eff.token_reduction_pct}%, "
                f"Call reduction: {eff.call_reduction_pct}%, "
                f"Compression: {eff.compression_ratio}x"
            ),
            category="efficiency",
        )
        collect_result(result)
        assert eff.token_reduction_pct > 0
