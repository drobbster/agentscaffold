"""Template rendering utilities.

Provides Jinja2 environment, default context, and graph-enriched context
for injecting knowledge graph data into templates and prompts.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import ChainableUndefined, Environment, PackageLoader, select_autoescape

from agentscaffold.config import ScaffoldConfig

logger = logging.getLogger(__name__)


def get_jinja_env() -> Environment:
    """Get Jinja2 environment configured for agentscaffold templates."""
    return Environment(
        loader=PackageLoader("agentscaffold", "templates"),
        autoescape=select_autoescape([]),
        undefined=ChainableUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(template_path: str, context: dict) -> str:  # type: ignore[type-arg]
    """Render a template with the given context."""
    env = get_jinja_env()
    template = env.get_template(template_path)
    return template.render(**context)


def get_default_context(config: ScaffoldConfig) -> dict:  # type: ignore[type-arg]
    """Build the default template context from a ScaffoldConfig."""
    domain_reviews: list[str] = config.gates.review_to_ready.domain_reviews
    domain_standards: list[str] = config.standards.domain
    domain_approval_gates: dict[str, list[str]] = {}

    return {
        "config": config,
        "project_name": config.framework.project_name,
        "date": date.today().isoformat(),
        "architecture_layers": config.framework.architecture_layers,
        "domains": config.domains,
        "domain_reviews": domain_reviews,
        "domain_standards": domain_standards,
        "domain_approval_gates": domain_approval_gates,
        "semi_autonomous_enabled": config.semi_autonomous.enabled,
    }


# ---------------------------------------------------------------------------
# Graph-enriched context helpers
# ---------------------------------------------------------------------------


def get_graph_context(config: ScaffoldConfig) -> dict[str, Any]:
    """Build graph-derived context for templates.

    Returns an empty dict (graceful degradation) if the graph is unavailable.
    Templates use conditional blocks: {% if graph_stats %} ... {% endif %}
    """
    try:
        from agentscaffold.graph import graph_available, open_graph
    except ImportError:
        return {}

    if not graph_available(config):
        return {}

    try:
        store = open_graph(config)
    except Exception:
        logger.debug("Graph unavailable for template context")
        return {}

    try:
        stats = store.get_stats()

        from agentscaffold.review.queries import (
            get_all_plans,
            get_hot_files,
            get_volatile_modules,
        )

        hot_files = get_hot_files(store, limit=10)
        volatile = get_volatile_modules(store)
        plans = get_all_plans(store)

        from agentscaffold.graph.query_compat import ql  # noqa: PLC0415
        from agentscaffold.review.filters import normalize_plan_status  # noqa: PLC0415

        # Architecture layers
        layers = ql(
            store,
            sql=(
                'SELECT number AS "l.number", name AS "l.name", description AS "l.description"'
                " FROM ArchitectureLayer ORDER BY number"
            ),
        )

        # Active contracts
        contracts = ql(
            store,
            sql='SELECT name AS "c.name", version AS "c.version" FROM Contract LIMIT 20',
        )

        return {
            "graph_stats": stats,
            "graph_hot_files": [
                {"path": h.get("f.path", ""), "plan_count": h.get("plan_count", 0)}
                for h in hot_files
            ],
            "graph_volatile_modules": [
                {"path": v.get("f.path", ""), "plan_count": v.get("plan_count", 0)}
                for v in volatile
                if v.get("plan_count", 0) >= 3
            ],
            "graph_plans": [
                {
                    "number": p.get("p.number"),
                    "title": p.get("p.title", ""),
                    "status": p.get("p.status", ""),
                    "status_normalized": normalize_plan_status(p.get("p.status", "")),
                }
                for p in plans[:20]
            ],
            "graph_layers": [
                {
                    "number": la.get("l.number"),
                    "name": la.get("l.name", ""),
                    "description": la.get("l.description", ""),
                }
                for la in layers
            ],
            "graph_contracts": [
                {"name": c.get("c.name", ""), "version": c.get("c.version", "")} for c in contracts
            ],
        }
    except Exception:
        logger.debug("Failed to build graph context", exc_info=True)
        return {}
    finally:
        store.close()


def get_review_context(
    config: ScaffoldConfig,
    plan_number: int,
    review_type: str = "all",
) -> dict[str, Any]:
    """Build review-specific context for a plan.

    review_type: brief, challenges, gaps, verify, retro, all
    Returns empty dict if graph unavailable (graceful degradation).
    """
    try:
        from agentscaffold.graph import graph_available, open_graph
    except ImportError:
        return {}

    if not graph_available(config):
        return {}

    try:
        store = open_graph(config)
    except Exception:
        return {}

    result: dict[str, Any] = {}

    try:
        if review_type in ("brief", "all"):
            from agentscaffold.review.brief import (
                format_brief_markdown,
                generate_brief,
            )

            brief = generate_brief(store, plan_number)
            result["review_brief"] = brief
            result["review_brief_md"] = format_brief_markdown(brief)

        if review_type in ("challenges", "all"):
            from agentscaffold.review.challenges import (
                format_challenges_markdown,
                generate_challenges,
            )

            challenges = generate_challenges(store, plan_number)
            result["adversarial_challenges"] = [
                {"category": c.category, "text": c.text, "severity": c.severity} for c in challenges
            ]
            result["adversarial_challenges_md"] = format_challenges_markdown(challenges)

        if review_type in ("gaps", "all"):
            from agentscaffold.review.gaps import (
                format_gaps_markdown,
                generate_gaps,
            )

            gaps = generate_gaps(store, plan_number)
            result["gap_analysis"] = [
                {"category": g.category, "text": g.text, "severity": g.severity} for g in gaps
            ]
            result["gap_analysis_md"] = format_gaps_markdown(gaps)

        if review_type in ("verify", "all"):
            from agentscaffold.review.verify import (
                format_verification_markdown,
                verify_implementation,
            )

            items = verify_implementation(store, plan_number)
            result["verification"] = [
                {"check": i.check, "status": i.status, "detail": i.detail} for i in items
            ]
            result["verification_md"] = format_verification_markdown(items)

        if review_type in ("retro", "all"):
            from agentscaffold.review.feedback import (
                format_retro_markdown,
                generate_retro_enrichment,
            )

            insights = generate_retro_enrichment(store, plan_number)
            result["retro_enrichment"] = [
                {"category": i.category, "text": i.text} for i in insights
            ]
            result["retro_enrichment_md"] = format_retro_markdown(insights)

    except Exception:
        logger.debug("Failed to build review context", exc_info=True)
    finally:
        store.close()

    return result


def write_if_missing(path: Path, content: str) -> bool:
    """Write *content* to *path* only if the file does not already exist.

    Returns True if the file was written, False if it was skipped.
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


# Sentinel markers delimiting the AgentScaffold-managed region inside an
# otherwise user/org-owned document (AGENTS.md, CLAUDE.md, .windsurfrules,
# .cursor/rules.md). Regeneration only ever touches the region between these
# markers; everything outside is preserved verbatim.
MANAGED_BLOCK_BEGIN = "<!-- BEGIN AGENTSCAFFOLD MANAGED SECTION -->"
MANAGED_BLOCK_END = "<!-- END AGENTSCAFFOLD MANAGED SECTION -->"
_MANAGED_BLOCK_NOTE = (
    "<!-- Managed by AgentScaffold. The content between these markers is "
    "regenerated by `scaffold agents ...`; edits inside the block are overwritten. "
    "Everything OUTSIDE the markers is always preserved. Delete both markers to "
    "take full ownership of this file (AgentScaffold will then append a fresh "
    "block instead of replacing). -->"
)


def render_managed_block(content: str) -> str:
    """Wrap *content* in AgentScaffold managed-section markers with a notice."""
    return (
        f"{MANAGED_BLOCK_BEGIN}\n"
        f"{_MANAGED_BLOCK_NOTE}\n\n"
        f"{content.strip()}\n\n"
        f"{MANAGED_BLOCK_END}"
    )


def write_managed_block(
    path: Path, content: str, *, force: bool = False, backup: bool = True
) -> str:
    """Write the AgentScaffold-managed section to *path* without destroying user content.

    These documents (AGENTS.md, CLAUDE.md, .windsurfrules, .cursor/rules.md) may
    already be owned and curated by an organization or user, so they are NEVER
    silently overwritten. *content* is the freshly generated body; it is stored
    inside ``MANAGED_BLOCK_BEGIN``/``MANAGED_BLOCK_END`` markers so future
    regenerations can refresh just that region.

    Behavior:
    - File does not exist: create it containing only the managed block. Returns ``"created"``.
    - File exists WITH the markers: replace only the region between them, leaving
      all other content untouched. Returns ``"block-updated"`` (or ``"unchanged"``).
    - File exists WITHOUT the markers (org/user-managed): append a fresh managed
      block at the end, preserving every existing byte. Returns ``"appended"``.
    - ``force=True``: replace the ENTIRE file with the managed block, writing a
      ``<name>.bak`` snapshot first (when ``backup``). Returns ``"overwritten"``.

    Returns one of ``"created"``, ``"appended"``, ``"block-updated"``,
    ``"unchanged"``, ``"overwritten"``.
    """
    return _upsert_block(
        path,
        render_managed_block(content),
        MANAGED_BLOCK_BEGIN,
        MANAGED_BLOCK_END,
        force=force,
        backup=backup,
    )


def _upsert_block(
    path: Path,
    block: str,
    begin_marker: str,
    end_marker: str,
    *,
    force: bool = False,
    backup: bool = True,
) -> str:
    """Insert or refresh a delimited *block* in *path* without destroying user content.

    Shared engine behind :func:`write_managed_block` (HTML-comment markers) and
    :func:`write_gitignore_block` (``#``-comment markers). See those wrappers for
    marker-specific behavior. Returns one of ``"created"``, ``"appended"``,
    ``"block-updated"``, ``"unchanged"``, ``"overwritten"``.
    """
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(block + "\n")
        return "created"

    existing = path.read_text()

    if force:
        if backup and existing.strip():
            path.with_suffix(path.suffix + ".bak").write_text(existing)
        path.write_text(block + "\n")
        return "overwritten"

    begin = existing.find(begin_marker)
    end = existing.find(end_marker)
    if begin != -1 and end != -1 and end > begin:
        end_full = end + len(end_marker)
        updated = existing[:begin] + block + existing[end_full:]
        if updated == existing:
            return "unchanged"
        path.write_text(updated)
        return "block-updated"

    # No valid markers: this file is owned by the user/org. Append, never clobber.
    prefix = existing if existing.endswith("\n") else existing + "\n"
    path.write_text(prefix + "\n" + block + "\n")
    return "appended"


# Managed .gitignore block. Uses ``#``-comment markers (a ``.gitignore`` treats
# ``<!-- ... -->`` as literal path patterns, so the HTML-comment markers above
# cannot be reused here). Patterns cover every runtime artifact the package
# writes into a consumer repo -- all under ``.scaffold/`` (graph DB, model cache,
# hook logs, index lock/stamp, schema-migration exports) plus the
# ``.venv-scaffold/`` dedicated-venv convention. ``*.duckdb``/``*.duckdb.wal``
# are belt-and-suspenders for a relocated ``graph.db_path``.
GITIGNORE_BLOCK_BEGIN = "# BEGIN AGENTSCAFFOLD MANAGED SECTION"
GITIGNORE_BLOCK_END = "# END AGENTSCAFFOLD MANAGED SECTION"
_GITIGNORE_BLOCK_NOTE = (
    "# Managed by AgentScaffold. Runtime artifacts (graph DB, model cache, logs,\n"
    "# locks) are regenerated by 'scaffold index' and safe to delete. Edits inside\n"
    "# this block are overwritten by 'scaffold init' / 'scaffold agents generate-all';\n"
    "# everything OUTSIDE the markers is always preserved. Delete both markers to take\n"
    "# full ownership (AgentScaffold will then append a fresh block instead)."
)
GITIGNORE_MANAGED_PATTERNS: tuple[str, ...] = (
    ".scaffold/",
    ".venv-scaffold/",
    "*.duckdb",
    "*.duckdb.wal",
)


def render_gitignore_block() -> str:
    """Wrap the managed ignore patterns in ``#``-comment markers with a notice."""
    patterns = "\n".join(GITIGNORE_MANAGED_PATTERNS)
    return (
        f"{GITIGNORE_BLOCK_BEGIN}\n"
        f"{_GITIGNORE_BLOCK_NOTE}\n"
        f"{patterns}\n"
        f"{GITIGNORE_BLOCK_END}"
    )


def write_gitignore_block(path: Path) -> str:
    """Ensure *path* (a ``.gitignore``) contains the AgentScaffold managed block.

    Never destructive: a project ``.gitignore`` is inherently co-owned, so this
    only ever creates the file, refreshes the region between the managed markers,
    or appends the block to the end -- it never wholesale-replaces user content
    (there is deliberately no ``force`` path here, unlike ``write_managed_block``).

    Returns one of ``"created"``, ``"appended"``, ``"block-updated"``,
    ``"unchanged"``.
    """
    return _upsert_block(
        path,
        render_gitignore_block(),
        GITIGNORE_BLOCK_BEGIN,
        GITIGNORE_BLOCK_END,
        force=False,
    )
