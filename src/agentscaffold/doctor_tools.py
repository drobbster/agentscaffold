"""Per-tool probing for ``scaffold doctor --tools``.

Every other check in :mod:`agentscaffold.doctor` inspects configuration. This
one calls the tools, because the failure it exists to catch is the one
configuration cannot show you: a tool that is registered, advertised, and
broken.

Three design points, each chosen against a specific way this could mislead:

**Reads by default.** A diagnostic that records findings has altered the record
it was asked to inspect. Write tools are skipped unless ``include_writes``, and
even then they run against a throwaway project rather than the user's graph.

**Busy is not broken.** Another process holding the graph -- an index running in
the next terminal -- is routine and transient. Reporting it as a failure would
make the command cry wolf during precisely the operation people run it around,
so :class:`GraphLockError` gets its own status. The Step A0 spike established
that this surfaces as a bounded error in ~65 ms rather than a hang, which is
what makes probing every tool viable at all.

**One tool cannot take down the table.** The deliverable is the whole matrix, so
each probe is isolated; a tool that raises is recorded and the run continues.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agentscaffold.mcp.registry import WRITE_TOOLS, tool_names

ProbeStatus = Literal["ok", "fail", "skip", "busy"]


@dataclass(frozen=True)
class ToolProbe:
    """One tool's result. Typed so CI can gate on it rather than grep output."""

    name: str
    status: ProbeStatus
    detail: str | None = None
    elapsed_ms: float = 0.0


#: Arguments that make each tool do real work without depending on the contents
#: of the graph. A probe asserting a *specific* answer would fail on an empty
#: project, which is not the question being asked -- "does this tool run" is.
#: Tools whose required argument is a plan number get one that need not exist:
#: a clean "no such plan" is a working tool.
_PROBE_ARGUMENTS: dict[str, dict[str, Any]] = {
    "symbol": {"symbol": "main"},
    "file_or_symbol": {"file_or_symbol": "README.md"},
    "query": {"query": "test"},
    "sql": {"sql": "SELECT 1"},
    "check": {"check": "plans"},
    "topic": {"topic": "test"},
    "pattern": {"pattern": "def "},
    "plan_number": {"plan_number": 1},
    "plan_a": {"plan_a": 1},
    # Needs its own entry even though plan_a could supply both: the loop visits
    # every required argument, so a missing key here falls through to the
    # `"probe"` string default and lands a non-numeric plan number in the SQL.
    "plan_b": {"plan_b": 2},
    "review_type": {"review_type": "probe"},
    "category": {"category": "probe"},
    "finding": {"finding": "probe"},
    "findings": {"findings": []},
    "finding_id": {"finding_id": "probe::none"},
    "resolution": {"resolution": "probe"},
    "item_id": {"item_id": "probe::none"},
}


def _arguments_for(name: str, working_path: Path) -> dict[str, Any]:
    """Build a plausible argument set for *name* from its declared schema.

    The schema wins over the table above wherever it is specific. An argument
    with an ``enum`` has exactly four acceptable values and guessing a fifth
    produces a rejection that looks like a broken tool -- which is what a
    hardcoded ``"plans"`` did to ``scaffold_validate`` on the first run.
    """
    from agentscaffold.mcp.registry import get_tool_spec

    spec = get_tool_spec(name)
    arguments: dict[str, Any] = {"working_path": str(working_path)}
    if spec is None:
        return arguments

    properties = spec.input_schema.get("properties", {})
    for required in spec.input_schema.get("required", []):
        declared = properties.get(required, {})
        choices = declared.get("enum")
        if choices:
            arguments[required] = choices[0]
            continue
        if required in _PROBE_ARGUMENTS:
            arguments.update(_PROBE_ARGUMENTS[required])
            continue
        arguments[required] = _by_declared_type(declared)
    return arguments


def _by_declared_type(declared: dict[str, Any]) -> Any:
    """A harmless value of whatever type the schema asks for."""
    return {
        "integer": 1,
        "number": 1,
        "boolean": False,
        "array": [],
        "object": {},
    }.get(str(declared.get("type")), "probe")


def _invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call one tool. Separate function so tests can substitute failure modes."""
    from agentscaffold.mcp.server import _dispatch_tool

    return _dispatch_tool(name, arguments)


def probe_tools(
    context: Any,
    *,
    include_writes: bool = False,
) -> list[ToolProbe]:
    """Run every registered tool once and report how each behaved.

    Ordered like the registry so two runs can be diffed. *context* is a
    :class:`~agentscaffold.doctor.DoctorContext`.
    """
    from agentscaffold.graph import GraphLockError

    project_root = Path(getattr(context, "project_root", Path.cwd()))

    # Built once for the whole run and torn down after, rather than per write
    # tool: creating a project per probe would make the write half of the table
    # dominate the command's runtime.
    with scratch_project() if include_writes else _no_scratch() as scratch:
        return [
            _probe_one(name, project_root, scratch, include_writes, GraphLockError)
            for name in tool_names()
        ]


@contextmanager
def _no_scratch() -> Iterator[None]:
    yield None


def _probe_one(
    name: str,
    project_root: Path,
    scratch: Path | None,
    include_writes: bool,
    lock_error: type[BaseException],
) -> ToolProbe:
    """Run a single tool and classify the outcome, never raising."""
    if name in WRITE_TOOLS:
        if not include_writes:
            return ToolProbe(
                name=name,
                status="skip",
                detail="write tool; use --include-writes to exercise it",
            )
        if scratch is None:
            return ToolProbe(
                name=name,
                status="skip",
                detail="write tool; could not create a scratch project to write into",
            )

    working_path = scratch if (name in WRITE_TOOLS and scratch) else project_root

    started = time.perf_counter()
    try:
        result = _invoke(name, _arguments_for(name, working_path))
        return _classify(name, result, (time.perf_counter() - started) * 1000)
    except lock_error as exc:
        return ToolProbe(
            name=name,
            status="busy",
            detail=f"graph held by another process; retry shortly ({exc})",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    except Exception as exc:  # noqa: BLE001 - the table is the deliverable
        elapsed = (time.perf_counter() - started) * 1000
        if _is_stale_schema(exc):
            # One out-of-date graph otherwise reports as a dozen broken tools.
            # The tools are fine; the database predates their schema, and saying
            # that once per tool buries the single action that fixes all of them.
            return ToolProbe(
                name=name,
                status="skip",
                detail="graph schema is out of date; run scaffold index",
                elapsed_ms=elapsed,
            )
        return ToolProbe(
            name=name,
            status="fail",
            detail=f"{type(exc).__name__}: {exc}",
            elapsed_ms=elapsed,
        )


def _is_stale_schema(exc: BaseException) -> bool:
    """True if *exc* is the graph missing a table the current code expects."""
    text = str(exc).lower()
    return "does not exist" in text and ("table" in text or "catalog" in text)


def _classify(name: str, result: Any, elapsed_ms: float) -> ToolProbe:
    """Turn a tool's payload into a verdict.

    A tool that answers "no such plan" is working. A tool that reports the graph
    is unavailable is not a broken tool either -- it is a missing graph, which
    the other doctor checks already cover, so it reads as a skip rather than
    adding a second alarm for one cause.
    """
    if not isinstance(result, dict):
        return ToolProbe(name=name, status="ok", elapsed_ms=elapsed_ms)

    error = result.get("error")
    if not error:
        return ToolProbe(name=name, status="ok", elapsed_ms=elapsed_ms)

    text = str(error).lower()
    if "graph" in text and ("not available" in text or "no graph" in text or "not built" in text):
        return ToolProbe(
            name=name,
            status="skip",
            detail="no graph in this project; run scaffold index",
            elapsed_ms=elapsed_ms,
        )
    if "busy" in text or "lock" in text:
        return ToolProbe(
            name=name,
            status="busy",
            detail=f"{error}; retry shortly",
            elapsed_ms=elapsed_ms,
        )

    # A tool that declines a probe argument cleanly is a working tool. This is
    # the judgement most likely to be wrong in either direction, so it stays
    # narrow: only the shapes that are unambiguously the tool answering.
    if result.get("missing_argument") or "not found" in text or "unknown plan" in text:
        return ToolProbe(name=name, status="ok", detail=str(error), elapsed_ms=elapsed_ms)

    return ToolProbe(name=name, status="fail", detail=str(error), elapsed_ms=elapsed_ms)


@contextmanager
def scratch_project() -> Iterator[Path | None]:
    """A disposable project with its own graph, for write probes to write into.

    Created rather than borrowed. Requiring the user to keep a project named
    "scratch" would make ``--include-writes`` useless for most installations and
    tempting to point at a real project; a temporary one with its own database
    makes "this cannot touch your governance data" a property of the design
    instead of a promise. Yields ``None`` if it cannot be built, so the caller
    skips rather than falling back to somewhere real.
    """
    directory: str | None = None
    try:
        directory = tempfile.mkdtemp(prefix="agentscaffold-probe-")
        root = Path(directory)
        (root / "docs" / "ai" / "plans").mkdir(parents=True, exist_ok=True)
        (root / "scaffold.yaml").write_text(
            f"project:\n  name: doctor-probe\ngraph:\n  db_path: {root / 'probe.duckdb'}\n"
        )
        yield root
    except Exception:  # noqa: BLE001
        yield None
    finally:
        if directory:
            shutil.rmtree(directory, ignore_errors=True)


def summarize(probes: list[ToolProbe]) -> dict[str, int]:
    """Counts per status, for the one-line summary under the table."""
    counts: dict[str, int] = {}
    for probe in probes:
        counts[probe.status] = counts.get(probe.status, 0) + 1
    return counts


__all__ = ["ToolProbe", "probe_tools", "summarize"]
