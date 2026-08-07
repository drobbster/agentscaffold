"""Template rendering utilities.

Provides Jinja2 environment, default context, and graph-enriched context
for injecting knowledge graph data into templates and prompts.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
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
        f"{MANAGED_BLOCK_BEGIN}\n{_MANAGED_BLOCK_NOTE}\n\n{content.strip()}\n\n{MANAGED_BLOCK_END}"
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
    status, updated = _plan_block(path, block, begin_marker, end_marker, force=force)

    if status == "unchanged" or updated is None:
        return status

    if status == "overwritten" and backup:
        existing = path.read_text()
        if existing.strip():
            path.with_suffix(path.suffix + ".bak").write_text(existing)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated)
    return status


def _plan_block(
    path: Path,
    block: str,
    begin_marker: str,
    end_marker: str,
    *,
    force: bool = False,
) -> tuple[str, str | None]:
    """Decide what :func:`_upsert_block` would do, without doing it.

    Split out so a dry run can predict the outcome from the same code that
    performs it. A predictor that reimplements the decision is a second source of
    truth, and the whole value of a dry run is that it cannot disagree with the
    real thing.

    Returns the status and the text that would be written (``None`` when nothing
    would be).
    """
    if not path.exists():
        return "created", block + "\n"

    existing = path.read_text()

    if force:
        return "overwritten", block + "\n"

    begin = existing.find(begin_marker)
    end = existing.find(end_marker)
    if begin != -1 and end != -1 and end > begin:
        end_full = end + len(end_marker)
        updated = existing[:begin] + block + existing[end_full:]
        if updated == existing:
            return "unchanged", None
        return "block-updated", updated

    # No valid markers: this file is owned by the user/org. Append, never clobber.
    prefix = existing if existing.endswith("\n") else existing + "\n"
    return "appended", prefix + "\n" + block + "\n"


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
    # Personal overlays (Plan 234): user-only agent prefs that must never become
    # team system-of-record. Ignore the *.local overlays, NOT the team AGENTS.md
    # / platform routing rules -- personalize via overlays, do not untrack shared
    # process files.
    "AGENTS.local.md",
    ".cursor/rules/local.*.mdc",
)


def render_gitignore_block() -> str:
    """Wrap the managed ignore patterns in ``#``-comment markers with a notice."""
    patterns = "\n".join(GITIGNORE_MANAGED_PATTERNS)
    return f"{GITIGNORE_BLOCK_BEGIN}\n{_GITIGNORE_BLOCK_NOTE}\n{patterns}\n{GITIGNORE_BLOCK_END}"


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


def gitignore_block_status(path: Path) -> str:
    """What :func:`write_gitignore_block` would return, without writing."""
    status, _ = _plan_block(
        path,
        render_gitignore_block(),
        GITIGNORE_BLOCK_BEGIN,
        GITIGNORE_BLOCK_END,
        force=False,
    )
    return status


# ---------------------------------------------------------------------------
# Canonical routing guidance (Plan 249 Phase B, ADR-025 Decision 6 as amended)
# ---------------------------------------------------------------------------
#
# One committed file at the workspace root is the source every per-project rule
# file is generated from. The copies keep their policy body inline -- editors
# inject them into agent context verbatim, so emptying them to a pointer would
# make the routing guidance conditional on an agent following it -- and each
# carries the canonical content hash so a stale or hand-edited copy is
# detectable instead of silently divergent.
#
# Emission is a shared_workspace feature. A lone or project_local repo has no
# workspace root to be canonical about, and per ADR-024 its generation is
# unchanged: no canonical file, no stamp, nothing to drift.

GUIDANCE_STAMP_KEY = "agentscaffold-guidance-sha256"

_GUIDANCE_STAMP_RE = re.compile(
    rf"<!--\s*{re.escape(GUIDANCE_STAMP_KEY)}:\s*(?P<sha>[0-9a-f]{{64}})\s+source:\s*(?P<source>\S+)\s*-->"
)

# Rule files generated from the canonical guidance, relative to a project root.
GUIDANCE_COPY_RELPATHS = (
    Path(".cursor") / "rules" / "agentscaffold.mdc",
    Path("CLAUDE.md"),
    Path(".windsurfrules"),
)


@dataclass(frozen=True)
class GuidanceStamp:
    """The canonical hash and source path recorded in a generated rule file."""

    sha256: str
    source: str


@dataclass(frozen=True)
class GuidanceDrift:
    """A generated rule file that no longer matches its canonical source.

    *reason* is ``"stale"`` (generated from an older canonical), ``"unstamped"``
    (hand-authored, or generated before Plan 249), or ``"missing_canonical"``
    (the source it cites is gone, so there is nothing to compare against).
    """

    path: Path
    reason: str
    expected: str | None = None
    found: str | None = None


def guidance_hash(text: str) -> str:
    """Return the content hash recorded in and compared against rule files."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_guidance_document(config: ScaffoldConfig) -> str:
    """Render the canonical routing guidance for *config*."""
    from agentscaffold.agents.rule_policy import generate_canonical_guidance_body  # noqa: PLC0415

    return generate_canonical_guidance_body(config)


def _shared_workspace_root(project_root: Path) -> tuple[Path, Any] | None:
    """Return (workspace_root, workspace) when *project_root* opts into sharing."""
    try:
        from agentscaffold.paths import load_workspace, resolve_workspace_root  # noqa: PLC0415

        workspace = load_workspace(project_root)
        if workspace.is_shared_workspace:
            return resolve_workspace_root(project_root), workspace
    except Exception:
        logger.debug("No shared workspace resolved from %s", project_root, exc_info=True)
    return None


def canonical_guidance_path(project_root: Path) -> Path | None:
    """Where the canonical guidance lives for *project_root*, if anywhere.

    Returns None for a lone or ``project_local`` repo, which has no workspace
    root and therefore no dedup relationship to maintain.
    """
    resolved = _shared_workspace_root(project_root)
    if resolved is None:
        return None
    workspace_root, workspace = resolved

    from agentscaffold.config import effective_asset_layout  # noqa: PLC0415

    layout = effective_asset_layout(workspace)
    return workspace_root / layout.shared.routing_guidance_file


def write_canonical_guidance(project_root: Path, config: ScaffoldConfig) -> tuple[Path, str] | None:
    """Write the canonical guidance for *project_root*'s workspace.

    Returns ``(path, status)`` where status is ``"created"``, ``"updated"`` or
    ``"unchanged"``, or None when the project is not in a shared workspace.
    """
    path = canonical_guidance_path(project_root)
    if path is None:
        return None

    content = canonical_guidance_document(config)
    if path.is_file():
        if path.read_text() == content:
            return path, "unchanged"
        status = "updated"
    else:
        status = "created"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path, status


def render_guidance_stamp(canonical_sha: str, source: str) -> str:
    """Render the provenance comment embedded in each generated rule file.

    An HTML comment because it has to survive unread in Markdown, in Cursor's
    ``.mdc``, and in ``.windsurfrules`` alike.
    """
    return f"<!-- {GUIDANCE_STAMP_KEY}: {canonical_sha} source: {source} -->"


def read_guidance_stamp(text: str) -> GuidanceStamp | None:
    """Parse the guidance stamp out of *text*, or None if it carries none."""
    match = _GUIDANCE_STAMP_RE.search(text)
    if match is None:
        return None
    return GuidanceStamp(sha256=match.group("sha"), source=match.group("source"))


def stamp_guidance(content: str, canonical_sha: str, source: str) -> str:
    """Append the guidance stamp to generated rule-file *content*.

    Appended rather than inserted so it cannot disturb the frontmatter Cursor
    requires on the first line of an ``.mdc``.
    """
    return f"{content.rstrip()}\n\n{render_guidance_stamp(canonical_sha, source)}\n"


def detect_guidance_drift(project_root: Path) -> list[GuidanceDrift]:
    """Report generated rule files that no longer match the canonical source.

    Empty for a lone repo, which has no canonical file by design.
    """
    canonical = canonical_guidance_path(project_root)
    if canonical is None:
        return []

    present = [
        project_root / relpath
        for relpath in GUIDANCE_COPY_RELPATHS
        if (project_root / relpath).is_file()
    ]

    if not canonical.is_file():
        return [GuidanceDrift(path=path, reason="missing_canonical") for path in present]

    expected = guidance_hash(canonical.read_text())

    drift: list[GuidanceDrift] = []
    for path in present:
        stamp = read_guidance_stamp(path.read_text())
        if stamp is None:
            drift.append(GuidanceDrift(path=path, reason="unstamped", expected=expected))
        elif stamp.sha256 != expected:
            drift.append(
                GuidanceDrift(path=path, reason="stale", expected=expected, found=stamp.sha256)
            )
    return drift
