"""Architecture layer conformance checking.

Implements the rule `AGENTS.md` states as a hard constraint: a component
consumes the output of its upstream layer and does not bypass intermediate
ones. Two import shapes break it.

An **inversion** runs upward -- a lower layer importing a higher one, so the
foundation depends on what is built on it. A **skip** reaches past an
intermediate layer, which is the bypass the constraint names directly.

The design point that matters most here is what happens when the check cannot
see. Layer membership needs two things in the same graph: layer definitions
parsed from ``system_architecture.md``, and code files whose paths match those
layers' patterns. A repository can easily have one without the other -- this
project is exactly that case, with the architecture document in a governance
repo and the code in a package repo -- and a check that answered "no
violations" from a graph containing no layered files would be reporting a clean
architecture on the strength of having looked at nothing. So the absence of
either half is a distinct ``not_evaluable`` status rather than a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LayerReport:
    """The outcome of a layer conformance check."""

    STATUSES = ("pass", "fail", "not_evaluable")

    status: str
    evaluable: bool
    reason: str = ""
    violations: list[dict[str, Any]] = field(default_factory=list)
    remediation: str | None = None
    layer_count: int = 0
    mapped_file_count: int = 0
    checked_import_count: int = 0
    unmapped_import_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evaluable": self.evaluable,
            "reason": self.reason,
            "violations": self.violations,
            "remediation": self.remediation,
            "layer_count": self.layer_count,
            "mapped_file_count": self.mapped_file_count,
            "checked_import_count": self.checked_import_count,
            "unmapped_import_count": self.unmapped_import_count,
        }


def _not_evaluable(reason: str, remediation: str | None = None, **counts: int) -> LayerReport:
    return LayerReport(
        status="not_evaluable",
        evaluable=False,
        reason=reason,
        remediation=remediation,
        **counts,
    )


def check_layers(
    store: Any, scope_sql: str = "", params: dict[str, Any] | None = None
) -> LayerReport:
    """Check every cross-layer import against the layering rule.

    *scope_sql* is an optional predicate fragment for project scoping in a
    multi-project workspace.
    """
    try:
        layers = _fetch_layers(store, scope_sql, params)
    except Exception as exc:  # noqa: BLE001 - a broken graph is not a clean one
        return _not_evaluable(f"The graph is unavailable: {exc}")

    if not layers:
        return _not_evaluable(
            "No architecture layers are defined, so there is nothing to check against.",
            remediation=(
                "Add docs/ai/system_architecture.md with numbered layers and their "
                "path patterns, then run scaffold index."
            ),
        )

    try:
        memberships = _fetch_memberships(store, scope_sql, params)
    except Exception as exc:  # noqa: BLE001
        return _not_evaluable(f"The graph is unavailable: {exc}", layer_count=len(layers))

    if not memberships:
        empty_patterns = _layers_have_empty_patterns(store, scope_sql, params)
        if empty_patterns:
            return _not_evaluable(
                f"{len(layers)} layers are defined but none declare path patterns, so "
                "no file can be mapped. This is no layer data ingested, not a clean "
                "architecture.",
                remediation=(
                    "Give each layer a Components table with a Paths column, a "
                    "**Paths**/**Location** line, or inline backticked repo paths, "
                    "then run scaffold index."
                ),
                layer_count=len(layers),
            )
        return _not_evaluable(
            f"{len(layers)} layers are defined but no files are mapped to them, so no "
            "import can be attributed to a layer.",
            remediation=(
                "Check that the path patterns in docs/ai/system_architecture.md match "
                "this project's layout. If the architecture document lives in a "
                "different repository from the code, neither graph holds both halves "
                "and this check cannot run."
            ),
            layer_count=len(layers),
        )

    try:
        imports = _fetch_imports(store, scope_sql, params)
    except Exception as exc:  # noqa: BLE001
        return _not_evaluable(
            f"The graph is unavailable: {exc}",
            layer_count=len(layers),
            mapped_file_count=len(memberships),
        )

    violations: list[dict[str, Any]] = []
    checked = 0
    unmapped = 0

    for edge in imports:
        source = edge.get("src")
        target = edge.get("dst")
        from_layer = memberships.get(source)
        to_layer = memberships.get(target)

        # An unmapped file carries no layer information. Inventing one -- by
        # defaulting to zero, or by treating the gap itself as a finding --
        # would manufacture a violation out of missing data.
        if from_layer is None or to_layer is None:
            unmapped += 1
            continue

        checked += 1
        violation = _classify(source, target, from_layer, to_layer)
        if violation is not None:
            violations.append(violation)

    violations.sort(key=lambda v: (v["from_file"], v["to_file"]))

    return LayerReport(
        status="fail" if violations else "pass",
        evaluable=True,
        reason="" if violations else "Every cross-layer import consumes the layer directly below.",
        violations=violations,
        layer_count=len(layers),
        mapped_file_count=len(memberships),
        checked_import_count=checked,
        unmapped_import_count=unmapped,
    )


def _classify(source: str, target: str, from_layer: int, to_layer: int) -> dict[str, Any] | None:
    """Return a violation for one import, or None if it is permitted."""
    if from_layer == to_layer:
        return None

    if to_layer > from_layer:
        return {
            "kind": "inversion",
            "from_file": source,
            "to_file": target,
            "from_layer": from_layer,
            "to_layer": to_layer,
            "detail": (
                f"Layer {from_layer} imports layer {to_layer}, so a lower layer "
                "depends on a higher one."
            ),
        }

    skipped = list(range(to_layer + 1, from_layer))
    if skipped:
        return {
            "kind": "skip",
            "from_file": source,
            "to_file": target,
            "from_layer": from_layer,
            "to_layer": to_layer,
            "skipped": skipped,
            "detail": (
                f"Layer {from_layer} imports layer {to_layer} directly, bypassing "
                f"layer{'s' if len(skipped) > 1 else ''} "
                f"{', '.join(str(n) for n in skipped)}."
            ),
        }

    return None


def _layers_have_empty_patterns(store: Any, scope_sql: str, params: dict[str, Any] | None) -> bool:
    """True when every ArchitectureLayer row has an empty pathPatterns value."""
    sql = "SELECT pathPatterns FROM ArchitectureLayer"
    if scope_sql:
        sql += f" WHERE {scope_sql}"
    try:
        rows = store.query(sql, params) if params else store.query(sql)
    except Exception:  # noqa: BLE001 - missing column is not empty-pattern evidence
        return False
    if not rows or not any("pathPatterns" in row for row in rows):
        return False
    return all(not str(row.get("pathPatterns") or "").strip() for row in rows)


def _fetch_layers(store: Any, scope_sql: str, params: dict[str, Any] | None) -> list[int]:
    sql = "SELECT number FROM ArchitectureLayer"
    if scope_sql:
        sql += f" WHERE {scope_sql}"
    rows = store.query(sql, params) if params else store.query(sql)
    numbers = []
    for row in rows or []:
        try:
            numbers.append(int(row["number"]))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(set(numbers))


def _fetch_memberships(store: Any, scope_sql: str, params: dict[str, Any] | None) -> dict[str, int]:
    sql = "SELECT src, dst FROM BELONGS_TO_LAYER"
    rows = store.query(sql, params) if params else store.query(sql)
    memberships: dict[str, int] = {}
    for row in rows or []:
        file_id = row.get("src")
        number = row.get("number")
        if number is None:
            # Edge rows carry the layer id; recover the number from it.
            dst = str(row.get("dst") or "")
            number = dst.rsplit("::", 1)[-1]
        try:
            memberships[file_id] = int(number)
        except (TypeError, ValueError):
            continue
    return memberships


def _fetch_imports(
    store: Any, scope_sql: str, params: dict[str, Any] | None
) -> list[dict[str, Any]]:
    sql = "SELECT src, dst FROM IMPORTS"
    rows = store.query(sql, params) if params else store.query(sql)
    return list(rows or [])


__all__ = ["LayerReport", "check_layers"]
