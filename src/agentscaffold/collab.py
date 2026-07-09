"""Collaboration ergonomics: file sharding + advisory plan claims (Plan 226).

High-contention governance files (``workflow_state.md``, ``backlog.md``) are
append-heavy single files, so concurrent agents/users collide on them
constantly. This module lets a repo (opt-in via ``collab.sharded``) store those
files as per-entry *fragments* and assemble them deterministically with
:func:`render_fragments`, so concurrent writers touch different files and git
rarely has to merge the same lines.

It also provides an *advisory*, git-backed plan-ownership convention
(:func:`claim_plan` / :func:`release_plan`): a claim is a small committed JSON
record, not an enforced lock. Two writers can still both edit; the claim simply
makes in-flight ownership visible (surfaced by ``scaffold plan status``).

Design rules:
- **Stable, exact round-trip.** :func:`split_file` writes ordered fragments whose
  concatenation reproduces the source byte-for-byte, and :func:`render_fragments`
  is its inverse. This mirrors the Plan 222 governance-artifact stability rule:
  rendering twice yields identical bytes, so diffs stay minimal.
- **Format-agnostic.** Splitting is purely textual (boundary regex), so the same
  machinery shards both ``workflow_state.md`` (``###`` headings) and
  ``backlog.md`` (``##`` headings) without understanding their semantics.
- **No new persistence of secrets / no network.** Fragments and claims are plain
  files under the repo, committed via git like everything else.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

#: Zero-padded width for fragment ordinal prefixes (e.g. ``0007_``). Five digits
#: keeps fragments lexically sortable well past any realistic entry count.
_ORDINAL_WIDTH = 5

#: Fragment filenames look like ``00007_some-slug.md``; the leading ordinal is
#: what render sorts on, so order is preserved independent of the slug text.
_FRAGMENT_RE = re.compile(r"^(\d+)_.*\.md$")

#: The preamble fragment (content before the first boundary) sorts first.
_PREAMBLE_SLUG = "preamble"


class CollabError(Exception):
    """Raised when a sharding/claim operation cannot be completed safely."""


# ---------------------------------------------------------------------------
# Fragment sharding (workflow_state / backlog)
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Return a short filesystem-safe slug for a heading line."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned[:48] or "entry"


def _fragment_name(ordinal: int, slug: str) -> str:
    return f"{ordinal:0{_ORDINAL_WIDTH}d}_{slug}.md"


def split_text(content: str, boundary: re.Pattern[str]) -> list[tuple[str, str]]:
    """Split *content* into ``(slug, chunk)`` pairs at lines matching *boundary*.

    The chunk before the first boundary is the preamble (slug ``preamble``);
    each subsequent chunk starts at a boundary line and runs up to the next
    boundary. Concatenating every chunk in order reproduces *content* exactly,
    so the split is lossless and reversible.
    """
    lines = content.splitlines(keepends=True)
    chunks: list[tuple[str, str]] = []
    current_slug = _PREAMBLE_SLUG
    current: list[str] = []

    for line in lines:
        if boundary.match(line):
            if current:
                chunks.append((current_slug, "".join(current)))
            current_slug = _slugify(line)
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append((current_slug, "".join(current)))
    return chunks


def split_file(source: Path, fragments_dir: Path, boundary: re.Pattern[str]) -> list[Path]:
    """Shard *source* into ordered fragment files under *fragments_dir*.

    Idempotent: existing ``NNNNN_*.md`` fragments are cleared first so re-splitting
    does not accumulate stale fragments. Reversible via :func:`render_fragments`.
    """
    if not source.is_file():
        raise CollabError(f"Cannot split: source file does not exist: {source}")
    content = source.read_text(encoding="utf-8")
    chunks = split_text(content, boundary)

    fragments_dir.mkdir(parents=True, exist_ok=True)
    for existing in fragments_dir.glob("*.md"):
        if _FRAGMENT_RE.match(existing.name):
            existing.unlink()

    written: list[Path] = []
    for ordinal, (slug, chunk) in enumerate(chunks):
        frag = fragments_dir / _fragment_name(ordinal, slug)
        frag.write_text(chunk, encoding="utf-8")
        written.append(frag)
    return written


def fragment_paths(fragments_dir: Path) -> list[Path]:
    """Return fragment files sorted by their numeric ordinal prefix."""
    if not fragments_dir.is_dir():
        return []
    frags = [p for p in fragments_dir.glob("*.md") if _FRAGMENT_RE.match(p.name)]

    def _ordinal(p: Path) -> int:
        m = _FRAGMENT_RE.match(p.name)
        return int(m.group(1)) if m else 0

    return sorted(frags, key=_ordinal)


def render_fragments(fragments_dir: Path) -> str:
    """Assemble fragments into a single document (inverse of :func:`split_file`).

    Deterministic: fragments are concatenated in ordinal order, so rendering is
    stable across machines and runs. Returns an empty string if no fragments
    exist.
    """
    return "".join(p.read_text(encoding="utf-8") for p in fragment_paths(fragments_dir))


def render_to_file(fragments_dir: Path, target: Path) -> bool:
    """Render fragments and write the result to *target* if it changed.

    Returns True if *target* was written (content differed or did not exist),
    False if it was already up to date. Writing only on change keeps git diffs
    and mtimes quiet, matching the Plan 222 stability rule.
    """
    rendered = render_fragments(fragments_dir)
    if target.is_file() and target.read_text(encoding="utf-8") == rendered:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    return True


#: Default boundary patterns for the two sharded governance files.
WORKFLOW_STATE_BOUNDARY = re.compile(r"^### ")
BACKLOG_BOUNDARY = re.compile(r"^## ")


# ---------------------------------------------------------------------------
# Advisory plan claims
# ---------------------------------------------------------------------------


def _claim_path(claims_dir: Path, plan_number: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(plan_number))
    return claims_dir / f"{safe}.json"


def claim_plan(claims_dir: Path, plan_number: str, owner: str) -> dict[str, str]:
    """Record advisory ownership of a plan; return the claim record.

    Raises :class:`CollabError` if the plan is already claimed by a *different*
    owner (re-claiming by the same owner just refreshes the timestamp). The
    claim is advisory: it is committed to git for visibility, not enforced.
    """
    existing = get_claim(claims_dir, plan_number)
    if existing is not None and existing.get("owner") != owner:
        raise CollabError(
            f"Plan {plan_number} is already claimed by '{existing.get('owner')}' "
            f"since {existing.get('claimed_at')}. Use 'release' first or coordinate."
        )
    record = {
        "plan": str(plan_number),
        "owner": owner,
        "claimed_at": datetime.now(timezone.utc).isoformat(),
    }
    claims_dir.mkdir(parents=True, exist_ok=True)
    path = _claim_path(claims_dir, plan_number)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def release_plan(claims_dir: Path, plan_number: str) -> bool:
    """Clear a plan claim. Returns True if a claim was removed, else False."""
    path = _claim_path(claims_dir, plan_number)
    if path.is_file():
        path.unlink()
        return True
    return False


def get_claim(claims_dir: Path, plan_number: str) -> dict[str, str] | None:
    """Return the claim record for a plan, or None if unclaimed."""
    path = _claim_path(claims_dir, plan_number)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise CollabError(f"Corrupt claim file {path}: {exc}") from exc
    return data if isinstance(data, dict) else None


def list_claims(claims_dir: Path) -> list[dict[str, str]]:
    """Return all current claims, sorted by plan identifier."""
    if not claims_dir.is_dir():
        return []
    claims: list[dict[str, str]] = []
    for path in sorted(claims_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            claims.append(data)
    return sorted(claims, key=lambda c: str(c.get("plan", "")))
