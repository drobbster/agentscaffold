"""Derive owner plan, layer, roadmap stage and ``since`` (contract v2, Derivation).

Derivation reads governance records the project already keeps: annotations in
each component's source, plan File Impact Maps and metadata, commit messages
that cite plans, the roadmap document, and two optional ``scaffold.yaml``
mappings. Rules run in a fixed order and each value records the rule that
produced it. A pin in the inventory file is never overwritten; it wins when
the effective view is built.

Git is read once per source file (``git log -p``), never per component, and
with fixed arguments and no shell. Without git history, ``since`` falls back
to today and commit citations are skipped.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from agentscaffold.inventory import paths as inv_paths
from agentscaffold.inventory import roadmap
from agentscaffold.inventory.collectors import Collected, CollectionResult
from agentscaffold.inventory.derived_file import Derived, DerivedEntry
from agentscaffold.inventory.schema import Component, Inventory
from agentscaffold.paths import vcs_root
from agentscaffold.repo_paths import is_repo_path, vcs_relative

logger = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 120
_PLAN_FILE = re.compile(r"^(\d+)[-_.]")
_LAYER_LINE = re.compile(
    r"^-\s+Architecture\s+Layers?(?:\(s\))?\s*:\s*(?P<value>.*)$", re.IGNORECASE | re.MULTILINE
)
_STAGE_LINE = re.compile(r"^-\s+Roadmap\s+Stage\s*:\s*(?P<value>.*)$", re.IGNORECASE | re.MULTILINE)
_PARENS = re.compile(r"\([^()]*\)")
_LAYER_TOKEN = re.compile(r"^(?:l|layer\s*)?(\d+)\b")
_CITATION = re.compile(r"\bplans?\s*#?\s*(\d{1,4})\b", re.IGNORECASE)
_NOT_SET = frozenset({"", "tbd", "none", "n/a", "na", "-"})


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


@dataclass
class PlanRecord:
    """What derivation needs from one plan file."""

    label: str
    number: int
    complete: bool
    layers: list[str] | str | None
    roadmap_stage: str | None
    files: list[tuple[str, bool]] = field(default_factory=list)


def _continued(text: str, start: int) -> str:
    """The metadata value starting at *start*, with its indented continuation lines."""
    end = text.find("\n", start)
    value = text[start : end if end != -1 else len(text)]
    while end != -1:
        nxt = text.find("\n", end + 1)
        line = text[end + 1 : nxt if nxt != -1 else len(text)]
        if not line.startswith((" ", "\t")) or line.lstrip().startswith("- "):
            break
        value += " " + line.strip()
        end = nxt
    return value


def plan_layers(text: str) -> list[str] | str | None:
    """Layer ids from ``- Architecture Layer(s):``; ``cross-cutting``; or None.

    Parenthetical notes are dropped, and the list ends at the first segment
    that names no layer (``... with read-only capture at 2`` adds nothing).
    """
    match = _LAYER_LINE.search(text[:8000])
    if match is None:
        return None
    value = _continued(text, match.start("value"))
    previous = None
    while previous != value:
        previous, value = value, _PARENS.sub(" ", value)
    ids: list[str] = []
    cross = False
    for segment in re.split(r"[,;+]|\band\b", value):
        token = segment.strip().strip("*`'\" ").lower()
        if token in _NOT_SET:
            continue
        found = _LAYER_TOKEN.match(token)
        if found:
            if found.group(1) not in ids:
                ids.append(found.group(1))
            continue
        if token.startswith("cross"):
            cross = True
            continue
        break
    if ids:
        return ids
    return "cross-cutting" if cross else None


def plan_roadmap_stage(text: str) -> str | None:
    match = _STAGE_LINE.search(text[:8000])
    if match is None:
        return None
    tokens = re.sub(r"[*`]", "", match.group("value")).split()
    if tokens and tokens[0].lower() == "stage":
        tokens = tokens[1:]
    stage = tokens[0].rstrip(".,:;") if tokens else ""
    return None if stage.lower() in _NOT_SET else stage


def _is_complete(status: str) -> bool:
    return status.strip().strip("*").lower().startswith(("complete", "done"))


def _created(change_type: str) -> bool:
    return change_type.strip().strip("*`").lower().startswith(("create", "new", "add"))


def plan_index(plans_dir: Path) -> dict[int, PlanRecord]:
    """Every plan in *plans_dir* by number."""
    from agentscaffold.graph.governance import (  # noqa: PLC0415
        _extract_file_impact,
        _extract_metadata,
    )

    out: dict[int, PlanRecord] = {}
    if not plans_dir.is_dir():
        return out
    for path in sorted(plans_dir.glob("*.md")):
        match = _PLAN_FILE.match(path.name)
        if match is None:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        number = int(match.group(1))
        status = _extract_metadata(text).get("status", "")
        files = [
            (_normal(row["path"]), _created(row.get("change_type", "")))
            for row in _extract_file_impact(text)
        ]
        out[number] = PlanRecord(
            label=match.group(1),
            number=number,
            complete=_is_complete(status),
            layers=plan_layers(text),
            roadmap_stage=plan_roadmap_stage(text),
            files=[(p, c) for p, c in files if p],
        )
    return out


def _normal(path: str) -> str:
    path = path.strip().strip("`")
    while path.startswith("./"):
        path = path[2:]
    return path


def _lists(fim_path: str, target: str) -> bool:
    """A File Impact Map path names *target* (same path, or a longer prefix of it)."""
    return fim_path == target or fim_path.endswith("/" + target)


# ---------------------------------------------------------------------------
# Git history
# ---------------------------------------------------------------------------


@dataclass
class Commit:
    sha: str
    date: str
    message: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def _parse_log(output: str) -> list[Commit]:
    commits: list[Commit] = []
    for chunk in output.split("\x00"):
        if not chunk.strip():
            continue
        parts = chunk.split("\x1f", 3)
        if len(parts) < 3:
            continue
        sha, date, message = parts[0].strip(), parts[1].strip(), parts[2]
        patch = parts[3] if len(parts) > 3 else ""
        commit = Commit(sha=sha, date=date, message=message)
        for line in patch.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                commit.added.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                commit.removed.append(line[1:])
        commits.append(commit)
    return commits


class GitHistory:
    """``git log -p`` per source file, oldest commit first, read once each."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._vcs = vcs_root(self._root)
        self._cache: dict[str, list[Commit]] = {}

    def _repo_relative(self, source: str) -> str | None:
        if self._vcs is None:
            return None
        if is_repo_path(source):
            return vcs_relative(source)
        disk = Path(os.path.realpath(self._root / source))
        try:
            return disk.relative_to(Path(os.path.realpath(self._vcs))).as_posix()
        except ValueError:
            return None

    def commits(self, source: str) -> list[Commit]:
        if source in self._cache:
            return self._cache[source]
        rel = self._repo_relative(source)
        commits: list[Commit] = []
        if rel is not None:
            cmd = [
                "git",
                "-C",
                str(self._vcs),
                "-c",
                "core.quotepath=off",
                "log",
                "--reverse",
                "--no-color",
                "--no-ext-diff",
                "--unified=0",
                "--date=short",
                "--format=%x00%H%x1f%ad%x1f%B%x1f",
                "-p",
                "--",
                rel,
            ]
            try:
                done = subprocess.run(  # noqa: S603 - fixed arguments, no shell
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=GIT_TIMEOUT_SECONDS,
                    check=False,
                )
                if done.returncode == 0:
                    commits = _parse_log(done.stdout)
                else:
                    logger.debug("git log failed for %s: %s", rel, done.stderr.strip())
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.debug("git log unavailable for %s: %s", rel, exc)
        self._cache[source] = commits
        return commits


def _token(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])")


def _defining(prefix: str, name: str) -> re.Pattern[str]:
    """The line that declares component *name* in a source of collector *prefix*."""
    quoted = rf"""["']?{re.escape(name)}["']?"""
    if prefix == "prefect":
        return re.compile(rf"^\s*-?\s*name:\s*{quoted}\s*(#.*)?$")
    if prefix == "compose":
        return re.compile(rf"^\s*{quoted}:\s*(#.*)?$")
    if prefix == "pyproject_scripts":
        return re.compile(rf"^\s*{quoted}\s*=")
    return _token(name)


def _whole_file(prefix: str) -> bool:
    """Collectors whose source declares one component, so every commit touches it."""
    return prefix == "github_workflows"


def _parts(component: Component | Collected) -> tuple[str, str, str]:
    cid = component.id or ""
    prefix = cid.split(":", 1)[0] if ":" in cid else ""
    return prefix, component.name or cid.split(":", 1)[-1], component.source or ""


def since(history: GitHistory, component: Component | Collected) -> str | None:
    """The date of the first commit that added the component's defining line."""
    prefix, name, source = _parts(component)
    if not source:
        return None
    commits = history.commits(source)
    if not commits:
        return None
    if not _whole_file(prefix):
        pattern = _defining(prefix, name)
        for commit in commits:
            if any(pattern.search(line) for line in commit.added):
                return commit.date
    return commits[0].date


def cited_plans(
    history: GitHistory, component: Component | Collected, known: set[int]
) -> list[int]:
    """Plan numbers cited by commits that changed the component, most recent first."""
    prefix, name, source = _parts(component)
    if not source:
        return []
    token = _token(name)
    out: list[int] = []
    for commit in reversed(history.commits(source)):
        if not _whole_file(prefix) and not any(
            token.search(line) for line in commit.added + commit.removed
        ):
            continue
        for match in _CITATION.finditer(commit.message):
            number = int(match.group(1))
            if number in known and number not in out:
                out.append(number)
    return out


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def component_files(component: Component) -> list[str]:
    """Files that define what the component runs: its entrypoint file, or a one-component source."""
    files: list[str] = []
    entry = inv_paths.entrypoint_path(component.entrypoint)
    if entry:
        files.append(_normal(entry))
    prefix = (component.id or "").split(":", 1)[0]
    if _whole_file(prefix) and component.source:
        files.append(_normal(component.source))
    return files


def _owner(
    component: Component,
    annotations: dict[str, str],
    plans: dict[int, PlanRecord],
    history: GitHistory,
) -> tuple[str | None, str | None, list[str]]:
    """``(owner label, rule, touched_by labels)``."""
    files = component_files(component)
    listing = sorted(
        {
            number
            for number, plan in plans.items()
            for path, _created in plan.files
            if any(_lists(path, f) for f in files)
        }
    )
    creators = sorted(
        number
        for number in listing
        if any(c and any(_lists(p, f) for f in files) for p, c in plans[number].files)
    )
    owner: int | None = None
    rule: str | None = None
    if annotations.get("owner_plan"):
        label = annotations["owner_plan"]
        touched = [plans[n].label for n in listing if plans[n].label != label]
        return label, "annotation", touched
    if creators:
        owner, rule = creators[0], "file_impact_map_create"
    elif listing:
        complete = [n for n in listing if plans[n].complete]
        owner, rule = (complete or listing)[-1], "file_impact_map"
    else:
        cited = cited_plans(history, component, set(plans))
        if cited:
            owner, rule = cited[0], "commit"
    touched = [plans[n].label for n in listing if n != owner]
    if owner is None:
        return None, None, touched
    return plans[owner].label, rule, touched


def _layer_from_paths(component: Component, layer_paths: dict[str, list[str]]) -> list[str]:
    candidates = component_files(component) + ([component.source] if component.source else [])
    hits: list[str] = []
    for layer_id, globs in layer_paths.items():
        for glob in globs:
            pattern = glob.rstrip("/")
            if any(fnmatch(f, pattern) or fnmatch(f, pattern + "/*") for f in candidates):
                if layer_id not in hits:
                    hits.append(layer_id)
                break
    return hits


def _owner_plan(plans: dict[int, PlanRecord], label: str | None) -> PlanRecord | None:
    if not label:
        return None
    try:
        return plans.get(int(label))
    except ValueError:
        return None


def derive_entry(
    component: Component,
    annotations: dict[str, str],
    plans: dict[int, PlanRecord],
    history: GitHistory,
    *,
    layer_paths: dict[str, list[str]],
    kind_layers: dict[str, str],
) -> DerivedEntry:
    """Every derived field for one component, by the contract's rule order."""
    entry = DerivedEntry()
    entry.owner_plan, entry.owner_from, entry.touched_by = _owner(
        component, annotations, plans, history
    )
    plan = _owner_plan(plans, entry.owner_plan)

    if annotations.get("layer"):
        entry.layer, entry.layer_from = annotations["layer"], "annotation"
    elif plan is not None and plan.layers:
        layers = plan.layers
        entry.layer = layers[0] if isinstance(layers, list) and len(layers) == 1 else layers
        entry.layer_from = "owner_plan"
    else:
        by_path = _layer_from_paths(component, layer_paths)
        if by_path:
            entry.layer = by_path[0] if len(by_path) == 1 else by_path
            entry.layer_from = "layer_paths"
        elif component.kind and kind_layers.get(component.kind):
            entry.layer, entry.layer_from = kind_layers[component.kind], "kind_layers"

    if annotations.get("roadmap_stage"):
        entry.roadmap_stage, entry.roadmap_stage_from = annotations["roadmap_stage"], "annotation"
    elif plan is not None and plan.roadmap_stage:
        entry.roadmap_stage, entry.roadmap_stage_from = plan.roadmap_stage, "owner_plan"
    return entry


def derive(
    root: Path,
    config: Any,
    inventory: Inventory,
    collected: CollectionResult,
    *,
    today: dt.date,
    history: GitHistory | None = None,
) -> Derived:
    """The derived file's content for *inventory* (the human file, not the effective view)."""
    root = Path(root)
    inv_cfg = config.inventory
    history = history or GitHistory(root)
    plans = plan_index(root / config.graph.plans_dir)
    found = collected.by_id()
    derived = Derived(generated_at=today.isoformat())
    stage_path = roadmap.find_roadmap(root, getattr(inv_cfg.roadmap, "path", None))
    stage = roadmap.read_current_stage(root, stage_path)
    if stage:
        derived.current_roadmap_stage, derived.current_roadmap_stage_from = stage, "roadmap"
    for component in inventory.components:
        if not component.id:
            continue
        hit = found.get(component.id)
        derived.components[component.id] = derive_entry(
            component,
            dict(hit.annotations) if hit else {},
            plans,
            history,
            layer_paths=dict(inv_cfg.layer_paths),
            kind_layers=dict(inv_cfg.kind_layers),
        )
    return derived


__all__ = [
    "Commit",
    "GitHistory",
    "PlanRecord",
    "cited_plans",
    "component_files",
    "derive",
    "derive_entry",
    "plan_index",
    "plan_layers",
    "plan_roadmap_stage",
    "since",
]
