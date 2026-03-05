"""Pre-review brief generator.

Produces a structured brief for a plan before any adversarial review begins.
Covers: dependency profile, historical context, related learnings,
layer analysis, and contract status for every file in the plan's impact map.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentscaffold.review.queries import (
    get_contracts_for_file,
    get_file_importers,
    get_file_layer,
    get_function_callers,
    get_learnings_for_file,
    get_plan_by_number,
    get_plan_impacted_files,
    get_plans_impacting_file,
    get_transitive_consumers,
)

if TYPE_CHECKING:
    from agentscaffold.graph.store import GraphStore


def generate_brief(store: GraphStore, plan_number: int) -> dict[str, Any]:
    """Generate a pre-review brief for the given plan.

    Returns a structured dict suitable for rendering into markdown or JSON.
    """
    plan = get_plan_by_number(store, plan_number)
    if plan is None:
        return {"error": f"Plan {plan_number} not found in graph."}

    impacted_files = get_plan_impacted_files(store, plan_number)

    file_profiles: list[dict[str, Any]] = []
    all_learnings: list[dict[str, Any]] = []
    all_prior_plans: list[dict[str, Any]] = []
    layers_touched: set[str] = set()
    total_direct_importers = 0
    total_transitive_consumers = 0
    total_callers = 0

    for frow in impacted_files:
        fpath = frow.get("f.path", "")
        if not fpath:
            continue

        importers = get_file_importers(store, fpath)
        callers = get_function_callers(store, fpath)
        transitive = get_transitive_consumers(store, fpath)
        prior_plans = get_plans_impacting_file(store, fpath)
        learnings = get_learnings_for_file(store, fpath)
        contracts = get_contracts_for_file(store, fpath)
        layer = get_file_layer(store, fpath)

        if layer:
            layers_touched.add(f"Layer {layer.get('l.number', '?')}: {layer.get('l.name', '?')}")

        total_direct_importers += len(importers)
        total_transitive_consumers += len(transitive)
        total_callers += len(callers)

        # Deduplicate learnings and prior plans
        for lr in learnings:
            lr_id = lr.get("lr.learningId", "")
            if lr_id and not any(x.get("lr.learningId") == lr_id for x in all_learnings):
                all_learnings.append(lr)

        for pp in prior_plans:
            pp_num = pp.get("p.number")
            if pp_num != plan_number and not any(
                x.get("p.number") == pp_num for x in all_prior_plans
            ):
                all_prior_plans.append(pp)

        file_profiles.append(
            {
                "path": fpath,
                "change_type": frow.get("r.changeType", ""),
                "direct_importers": len(importers),
                "transitive_consumers": len(transitive),
                "external_callers": len(callers),
                "prior_plan_count": len(
                    [p for p in prior_plans if p.get("p.number") != plan_number]
                ),
                "contract_count": len(contracts),
                "contracts": [
                    {"name": c.get("c.name", ""), "version": c.get("c.version", "")}
                    for c in contracts
                ],
                "layer": (
                    f"Layer {layer.get('l.number', '?')}: {layer.get('l.name', '?')}"
                    if layer
                    else None
                ),
            }
        )

    # Frequency analysis for prior plans
    plan_frequency_signal = ""
    if len(all_prior_plans) >= 3:
        plan_frequency_signal = (
            f"{len(all_prior_plans)} prior plans have modified these files. "
            "High modification frequency may indicate architectural instability."
        )

    return {
        "plan": {
            "number": plan.get("p.number"),
            "title": plan.get("p.title", ""),
            "status": plan.get("p.status", ""),
            "type": plan.get("p.planType", ""),
        },
        "file_profiles": file_profiles,
        "summary": {
            "files_impacted": len(impacted_files),
            "total_direct_importers": total_direct_importers,
            "total_transitive_consumers": total_transitive_consumers,
            "total_external_callers": total_callers,
            "layers_touched": sorted(layers_touched),
            "related_learnings": len(all_learnings),
            "prior_plans": len(all_prior_plans),
            "frequency_signal": plan_frequency_signal,
        },
        "learnings": [
            {
                "id": lr.get("lr.learningId", ""),
                "plan": lr.get("lr.planNumber"),
                "description": lr.get("lr.description", ""),
                "status": lr.get("lr.status", ""),
            }
            for lr in all_learnings
        ],
        "prior_plans": [
            {
                "number": pp.get("p.number"),
                "title": pp.get("p.title", ""),
                "status": pp.get("p.status", ""),
                "date": pp.get("p.createdDate", ""),
            }
            for pp in all_prior_plans
        ],
    }


def format_brief_markdown(brief: dict[str, Any]) -> str:
    """Render a brief dict as human-readable markdown."""
    if "error" in brief:
        return f"Error: {brief['error']}"

    plan = brief["plan"]
    summary = brief["summary"]
    lines: list[str] = []

    lines.append(f"# REVIEW BRIEF: Plan {plan['number']} ({plan['title']})")
    lines.append("")

    # Dependency summary
    lines.append("## Dependency Profile")
    lines.append("")
    lines.append(f"- Files impacted: {summary['files_impacted']}")
    lines.append(f"- Direct importers across all files: {summary['total_direct_importers']}")
    lines.append(f"- Transitive consumers (2-hop): {summary['total_transitive_consumers']}")
    lines.append(f"- External callers into these files: {summary['total_external_callers']}")
    lines.append(f"- Layers touched: {', '.join(summary['layers_touched']) or 'none detected'}")
    lines.append("")

    # Per-file profiles
    if brief["file_profiles"]:
        lines.append("## File-by-File Profile")
        lines.append("")
        for fp in brief["file_profiles"]:
            lines.append(f"### {fp['path']} ({fp['change_type']})")
            lines.append(
                f"  - {fp['direct_importers']} direct importers, "
                f"{fp['transitive_consumers']} transitive consumers"
            )
            lines.append(f"  - {fp['external_callers']} external callers")
            if fp["layer"]:
                lines.append(f"  - Layer: {fp['layer']}")
            if fp["contracts"]:
                for c in fp["contracts"]:
                    lines.append(f"  - Contract: {c['name']} v{c['version']}")
            lines.append("")

    # Historical context
    if brief["prior_plans"]:
        lines.append("## Historical Context")
        lines.append("")
        lines.append("Plans that previously modified these files:")
        lines.append("")
        for pp in brief["prior_plans"]:
            lines.append(f"- Plan {pp['number']} ({pp['date']}): {pp['title']} [{pp['status']}]")
        lines.append("")
        if summary["frequency_signal"]:
            lines.append(f"**Signal**: {summary['frequency_signal']}")
            lines.append("")

    # Related learnings
    if brief["learnings"]:
        lines.append("## Related Learnings")
        lines.append("")
        for lr in brief["learnings"]:
            lines.append(f"- {lr['id']}: {lr['description']} [{lr['status']}]")
        lines.append("")

    return "\n".join(lines)
