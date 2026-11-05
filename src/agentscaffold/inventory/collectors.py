"""Collectors: what the repository's files declare (contract v1, Collectors).

A collector reads source files and lists the components they declare. It never
calls a runtime. Each collector has a name (the id prefix), the kinds it
produces, and default source globs; projects choose which run and where they
look. Domain packs or projects may register more with :func:`register_collector`.
"""

from __future__ import annotations

import json
import logging
import posixpath
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agentscaffold.inventory import paths as inv_paths
from agentscaffold.paths import vcs_root
from agentscaffold.repo_paths import is_repo_path, vcs_relative

logger = logging.getLogger(__name__)


@dataclass
class Collected:
    """One component a source file declares."""

    id: str
    kind: str
    name: str
    source: str
    entrypoint: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    paused: bool = False

    def parameters_key(self) -> str:
        return json.dumps(self.parameters, sort_keys=True, default=str)


@dataclass
class CollectionResult:
    """Everything the enabled collectors found, and what they could not read."""

    components: list[Collected] = field(default_factory=list)
    collectors: list[str] = field(default_factory=list)
    kinds: set[str] = field(default_factory=set)
    sources_read: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def by_id(self) -> dict[str, Collected]:
        return {c.id: c for c in self.components}


Reader = Callable[[str, str], list[Collected]]


@dataclass(frozen=True)
class CollectorSpec:
    name: str
    kinds: frozenset[str]
    default_sources: tuple[str, ...]
    read: Reader


_REGISTRY: dict[str, CollectorSpec] = {}


def register_collector(
    name: str, kinds: set[str] | frozenset[str], default_sources: list[str], read: Reader
) -> None:
    """Add a collector. ``read(source_path, text)`` returns the components it declares."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError(f"collector name {name!r} must be lowercase letters, digits or _")
    _REGISTRY[name] = CollectorSpec(name, frozenset(kinds), tuple(default_sources), read)


def registered() -> dict[str, CollectorSpec]:
    return dict(_REGISTRY)


def collector_for(component_id: str) -> str | None:
    """The registered collector an id's prefix names, if any."""
    prefix = component_id.split(":", 1)[0] if ":" in component_id else ""
    return prefix if prefix in _REGISTRY else None


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------


def expand_sources(root: Path, globs: list[str]) -> list[tuple[str, Path]]:
    """``(inventory path, file)`` for each file the globs match, in sorted order.

    A glob is a project-relative or ``@repo/`` path; an invalid one is skipped.
    """
    out: dict[str, Path] = {}
    for glob in globs:
        if inv_paths.path_problem(glob) is not None:
            logger.warning("inventory source %r skipped: %s", glob, inv_paths.path_problem(glob))
            continue
        if is_repo_path(glob):
            base = vcs_root(root)
            pattern = vcs_relative(glob)
        else:
            base, pattern = root, glob
        if base is None:
            continue
        matches = (
            sorted(base.glob(pattern)) if any(c in pattern for c in "*?[") else [base / pattern]
        )
        for match in matches:
            if not match.is_file():
                continue
            form = inv_paths.to_inventory_path(root, match)
            if form is not None:
                out.setdefault(form, match)
    return sorted(out.items())


def _rebase(source: str, relative: str) -> str:
    """A path written relative to *source*'s directory, in inventory form."""
    if is_repo_path(source):
        joined = posixpath.normpath(
            posixpath.join(posixpath.dirname(vcs_relative(source)), relative)
        )
        return "@repo/" + joined
    directory = posixpath.dirname(source)
    return posixpath.normpath(posixpath.join(directory, relative)) if directory else relative


def collect(root: Path, collectors: list[tuple[str, list[str]]]) -> CollectionResult:
    """Run each named collector over its source globs (defaults when empty)."""
    result = CollectionResult()
    for name, globs in collectors:
        spec = _REGISTRY.get(name)
        if spec is None:
            result.problems.append(f"unknown collector {name!r}")
            continue
        result.collectors.append(name)
        result.kinds |= spec.kinds
        for source, disk in expand_sources(root, list(globs) or list(spec.default_sources)):
            try:
                text = disk.read_text(encoding="utf-8")
                found = spec.read(source, text)
            except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
                result.problems.append(f"{name}: cannot read {source}: {exc}")
                continue
            result.sources_read.append(source)
            result.components.extend(found)
    return result


# ---------------------------------------------------------------------------
# Shipped collectors
# ---------------------------------------------------------------------------


def _mapping(text: str, source: str) -> dict[str, Any]:
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{source} is not a YAML mapping")
    return data


def _has_schedule(deployment: dict[str, Any]) -> bool:
    schedules = deployment.get("schedules")
    if schedules is None and deployment.get("schedule") is not None:
        schedules = [deployment.get("schedule")]
    if not isinstance(schedules, list):
        return False
    return any(isinstance(s, dict) and s for s in schedules)


def _is_paused(deployment: dict[str, Any]) -> bool:
    if deployment.get("paused") is True:
        return True
    schedules = deployment.get("schedules")
    if isinstance(schedules, list) and schedules:
        entries = [s for s in schedules if isinstance(s, dict)]
        return bool(entries) and all(s.get("active") is False for s in entries)
    return False


def read_prefect(source: str, text: str) -> list[Collected]:
    """Deployments in a ``prefect.yaml``: ``scheduled_job`` with a schedule, else ``manual_job``."""
    out: list[Collected] = []
    for item in _mapping(text, source).get("deployments") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        name = str(item["name"]).strip()
        entry = item.get("entrypoint")
        entrypoint = None
        if isinstance(entry, str) and entry.strip():
            file_part = inv_paths.entrypoint_path(entry)
            entrypoint = entry.strip()
            if file_part is not None:
                entrypoint = _rebase(source, file_part) + entry.strip()[len(file_part) :]
        params = item.get("parameters")
        out.append(
            Collected(
                id=f"prefect:{name}",
                kind="scheduled_job" if _has_schedule(item) else "manual_job",
                name=name,
                source=source,
                entrypoint=entrypoint,
                parameters=params if isinstance(params, dict) else {},
                paused=_is_paused(item),
            )
        )
    return out


def read_compose(source: str, text: str) -> list[Collected]:
    """Services in a docker compose file."""
    out: list[Collected] = []
    services = _mapping(text, source).get("services") or {}
    if not isinstance(services, dict):
        return out
    for name, spec in services.items():
        command = spec.get("command") if isinstance(spec, dict) else None
        if isinstance(command, list):
            command = " ".join(str(part) for part in command)
        out.append(
            Collected(
                id=f"compose:{name}",
                kind="service",
                name=str(name),
                source=source,
                entrypoint=str(command).strip() if command else None,
            )
        )
    return out


def read_github_workflow(source: str, text: str) -> list[Collected]:
    """One ``workflow`` per file under ``.github/workflows``, named by its file stem."""
    _mapping(text, source)
    stem = posixpath.splitext(posixpath.basename(source))[0]
    return [Collected(id=f"github_workflows:{stem}", kind="workflow", name=stem, source=source)]


_SCRIPTS_HEADER = re.compile(r"^\s*\[project\.scripts\]\s*$")
_TABLE_HEADER = re.compile(r"^\s*\[")
_SCRIPT_LINE = re.compile(r"""^\s*["']?([A-Za-z0-9_.\-]+)["']?\s*=\s*["']([^"']+)["']""")


def _toml_scripts(text: str) -> dict[str, str]:
    if sys.version_info >= (3, 11):
        import tomllib  # noqa: PLC0415

        data = tomllib.loads(text)
        scripts = (data.get("project") or {}).get("scripts") or {}
        return {str(k): str(v) for k, v in scripts.items()}
    scripts_out: dict[str, str] = {}
    inside = False
    for line in text.splitlines():
        if _SCRIPTS_HEADER.match(line):
            inside = True
            continue
        if inside and _TABLE_HEADER.match(line):
            break
        match = _SCRIPT_LINE.match(line) if inside else None
        if match:
            scripts_out[match.group(1)] = match.group(2)
    return scripts_out


def read_pyproject_scripts(source: str, text: str) -> list[Collected]:
    """Console scripts in ``[project.scripts]``."""
    return [
        Collected(
            id=f"pyproject_scripts:{name}",
            kind="script",
            name=name,
            source=source,
            entrypoint=target,
        )
        for name, target in sorted(_toml_scripts(text).items())
    ]


register_collector("prefect", {"scheduled_job", "manual_job"}, ["prefect.yaml"], read_prefect)
register_collector(
    "compose",
    {"service"},
    ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"],
    read_compose,
)
register_collector(
    "github_workflows",
    {"workflow"},
    [".github/workflows/*.yml", ".github/workflows/*.yaml"],
    read_github_workflow,
)
register_collector("pyproject_scripts", {"script"}, ["pyproject.toml"], read_pyproject_scripts)
