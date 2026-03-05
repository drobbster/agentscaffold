"""Phase 4: Governance artifact ingestion.

Parses markdown-based governance artifacts (plans, contracts, learnings,
review findings) and creates corresponding graph nodes and edges.

Artifacts follow AgentScaffold template conventions:
- Plans:     docs/ai/plans/plan_NNN_*.md
- Contracts: docs/ai/contracts/*.md
- Learnings: docs/ai/state/learnings_tracker.md
- Findings:  embedded in plan appendices or standalone review files
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscaffold.graph.store import GraphStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

_PLAN_METADATA_RE = re.compile(
    r"^\|\s*(?P<key>[^|]+?)\s*\|\s*(?P<value>[^|]+?)\s*\|",
    re.MULTILINE,
)
_PLAN_NUMBER_RE = re.compile(r"plan[_\-]?0*(\d+)", re.IGNORECASE)
_FILE_IMPACT_ROW_RE = re.compile(
    r"^\|\s*(?!File\s|---)[`]?(?P<path>[^|`]+?)[`]?\s*\|" r"\s*(?P<change_type>[^|]+?)\s*\|",
    re.MULTILINE,
)
_HEADER_VALUES = {"File", "Change Type", "Description", "---"}


def _extract_plan_number(filename: str) -> int | None:
    """Extract the plan number from a filename like plan_042_data_loader.md."""
    m = _PLAN_NUMBER_RE.search(filename)
    return int(m.group(1)) if m else None


def _extract_metadata(text: str) -> dict[str, str]:
    """Extract key-value metadata from a markdown table at the top of a plan."""
    meta: dict[str, str] = {}
    for m in _PLAN_METADATA_RE.finditer(text[:3000]):
        key = m.group("key").strip().lower().replace(" ", "_")
        value = m.group("value").strip()
        if key and value and value != "---":
            meta[key] = value
    return meta


def _extract_file_impact(text: str) -> list[dict[str, str]]:
    """Extract files from the File Impact Map table."""
    impacts: list[dict[str, str]] = []
    section_start = text.find("## File Impact Map")
    if section_start == -1:
        section_start = text.find("## File impact map")
    if section_start == -1:
        return impacts

    next_section = text.find("\n## ", section_start + 20)
    section = text[section_start:next_section] if next_section != -1 else text[section_start:]

    for m in _FILE_IMPACT_ROW_RE.finditer(section):
        path = m.group("path").strip()
        change_type = m.group("change_type").strip()
        if (
            path
            and path not in _HEADER_VALUES
            and not path.startswith("---")
            and change_type
            and change_type not in _HEADER_VALUES
        ):
            impacts.append({"path": path, "change_type": change_type})
    return impacts


def _parse_plan(filepath: Path) -> dict[str, Any] | None:
    """Parse a single plan file into structured data."""
    try:
        text = filepath.read_text(errors="replace")
    except OSError:
        return None

    number = _extract_plan_number(filepath.name)
    if number is None:
        return None

    meta = _extract_metadata(text)

    # Title extraction: first H1 or metadata title
    title = meta.get("title", "")
    if not title:
        h1 = re.search(r"^#\s+(.+)", text, re.MULTILINE)
        if h1:
            title = h1.group(1).strip()

    status = meta.get("status", "unknown")
    plan_type = meta.get("type", meta.get("plan_type", "feature"))
    created = meta.get("created", meta.get("date", ""))
    last_updated = meta.get("last_updated", created)

    impacts = _extract_file_impact(text)

    return {
        "number": number,
        "title": title,
        "status": status,
        "plan_type": plan_type,
        "filepath": str(filepath),
        "created": created,
        "last_updated": last_updated,
        "file_impacts": impacts,
    }


# ---------------------------------------------------------------------------
# Contract parsing
# ---------------------------------------------------------------------------

_CONTRACT_VERSION_RE = re.compile(r"version\s*\|?\s*v?(\d+\.\d+)", re.IGNORECASE)
_CONTRACT_METHOD_RE = re.compile(
    r"^\s+def\s+(?P<name>\w+)\s*\(",
    re.MULTILINE,
)
_CONTRACT_CLASS_RE = re.compile(
    r"^class\s+(?P<name>\w+)",
    re.MULTILINE,
)


def _extract_contract_declarations(text: str) -> dict[str, list[str]]:
    """Extract class and method declarations from code blocks in contract markdown.

    Returns {"classes": [...], "methods": [...]} with unique names.
    """
    classes: list[str] = []
    methods: list[str] = []

    # Find fenced code blocks (```python ... ```)
    in_code = False
    code_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") and not in_code:
            in_code = True
            code_lines = []
            continue
        elif stripped.startswith("```") and in_code:
            in_code = False
            code_block = "\n".join(code_lines)
            for m in _CONTRACT_CLASS_RE.finditer(code_block):
                classes.append(m.group("name"))
            for m in _CONTRACT_METHOD_RE.finditer(code_block):
                methods.append(m.group("name"))
            continue
        if in_code:
            code_lines.append(line)

    return {
        "classes": sorted(set(classes)),
        "methods": sorted(set(methods)),
    }


def _parse_contract(filepath: Path) -> dict[str, Any] | None:
    """Parse a contract markdown file."""
    try:
        text = filepath.read_text(errors="replace")
    except OSError:
        return None

    name = filepath.stem.replace("_interface", "").replace("_", " ").title()

    version_m = _CONTRACT_VERSION_RE.search(text[:2000])
    version = version_m.group(1) if version_m else "0.0"

    meta = _extract_metadata(text)
    last_updated = meta.get("last_updated", meta.get("version_date", ""))
    declarations = _extract_contract_declarations(text)

    return {
        "name": name,
        "version": version,
        "filepath": str(filepath),
        "last_updated": last_updated,
        "declared_classes": declarations["classes"],
        "declared_methods": declarations["methods"],
    }


# ---------------------------------------------------------------------------
# Learnings parsing
# ---------------------------------------------------------------------------

_LEARNING_RE = re.compile(
    r"^\|\s*(?P<id>L\d+-\d+)\s*\|"
    r"\s*(?P<plan>\d+)\s*\|"
    r"\s*(?P<desc>[^|]+?)\s*\|"
    r"\s*(?P<target>[^|]+?)\s*\|"
    r"\s*(?P<status>[^|]+?)\s*\|",
    re.MULTILINE,
)


def _parse_learnings(filepath: Path) -> list[dict[str, Any]]:
    """Parse the learnings tracker markdown table."""
    try:
        text = filepath.read_text(errors="replace")
    except OSError:
        return []

    learnings: list[dict[str, Any]] = []
    for m in _LEARNING_RE.finditer(text):
        learning_id = m.group("id").strip()
        plan_number = int(m.group("plan").strip())
        description = m.group("desc").strip()
        target = m.group("target").strip()
        status = m.group("status").strip()
        if learning_id and description:
            learnings.append(
                {
                    "learning_id": learning_id,
                    "plan_number": plan_number,
                    "description": description,
                    "target": target,
                    "status": status,
                }
            )
    return learnings


# ---------------------------------------------------------------------------
# Review finding parsing
# ---------------------------------------------------------------------------

_FINDING_RE = re.compile(
    r"\[(?P<category>DEPENDENCY|HISTORY|LEARNING|LAYER|CONTRACT|PATTERN|CONSUMER|PERFORMANCE|"
    r"FINDING|RISK|GAP|EDGE_CASE)\]\s*(?P<text>[^\n]+(?:\n(?!\[)[^\n]+)*)",
    re.MULTILINE,
)


def _parse_review_findings(text: str, plan_number: int, review_type: str) -> list[dict[str, Any]]:
    """Extract structured review findings from review text."""
    findings: list[dict[str, Any]] = []
    for i, m in enumerate(_FINDING_RE.finditer(text)):
        findings.append(
            {
                "plan_number": plan_number,
                "review_type": review_type,
                "category": m.group("category").strip(),
                "finding": m.group("text").strip()[:500],
                "severity": "medium",
                "resolution": "",
                "status": "open",
                "index": i,
            }
        )
    return findings


# ---------------------------------------------------------------------------
# Pipeline phase: ingest governance artifacts
# ---------------------------------------------------------------------------


def process_governance(
    store: GraphStore,
    root: Path,
) -> dict[str, Any]:
    """Ingest governance artifacts into the graph.

    Scans standard AgentScaffold directories for plans, contracts,
    learnings, and review findings.

    Returns summary with counts.
    """
    plans_dir = root / "docs" / "ai" / "plans"
    contracts_dir = root / "docs" / "ai" / "contracts"
    learnings_file = root / "docs" / "ai" / "state" / "learnings_tracker.md"

    plan_count = 0
    contract_count = 0
    learning_count = 0
    finding_count = 0
    impact_edge_count = 0

    # File ID lookup for linking governance -> code nodes
    file_id_map: dict[str, str] = {}
    for row in store.query("MATCH (f:File) RETURN f.id, f.path"):
        file_id_map[row["f.path"]] = row["f.id"]

    # --- Plans ---
    if plans_dir.is_dir():
        for plan_file in sorted(plans_dir.glob("plan_*.md")):
            data = _parse_plan(plan_file)
            if data is None:
                continue

            plan_id = f"plan::{data['number']}"
            store.create_node(
                "Plan",
                {
                    "id": plan_id,
                    "number": data["number"],
                    "title": data["title"],
                    "status": data["status"],
                    "planType": data["plan_type"],
                    "filePath": data["filepath"],
                    "createdDate": data["created"],
                    "lastUpdated": data["last_updated"],
                },
            )
            plan_count += 1

            for impact in data["file_impacts"]:
                fpath = impact["path"]
                if fpath in file_id_map:
                    store.create_edge(
                        "PLAN_IMPACTS",
                        "Plan",
                        plan_id,
                        "File",
                        file_id_map[fpath],
                        {"changeType": impact["change_type"]},
                    )
                    impact_edge_count += 1

    # --- Contracts ---
    declares_edge_count = 0
    if contracts_dir.is_dir():
        for contract_file in sorted(contracts_dir.glob("*.md")):
            if contract_file.name in ("README.md", "contract_template.md"):
                continue
            data = _parse_contract(contract_file)
            if data is None:
                continue

            contract_id = f"contract::{contract_file.stem}"
            store.create_node(
                "Contract",
                {
                    "id": contract_id,
                    "name": data["name"],
                    "version": data["version"],
                    "filePath": data["filepath"],
                    "lastUpdated": data["last_updated"],
                    "declaredMethods": ",".join(data.get("declared_methods", [])),
                    "declaredClasses": ",".join(data.get("declared_classes", [])),
                },
            )
            contract_count += 1

            # Link contract to code definitions it declares
            for method_name in data.get("declared_methods", []):
                fn_rows = store.query(
                    f"MATCH (fn:Function) WHERE fn.name = '{method_name}' RETURN fn.id LIMIT 1"
                )
                if fn_rows:
                    store.create_edge(
                        "CONTRACT_DECLARES_FUNC",
                        "Contract",
                        contract_id,
                        "Function",
                        fn_rows[0]["fn.id"],
                    )
                    declares_edge_count += 1

            for class_name in data.get("declared_classes", []):
                cls_rows = store.query(
                    f"MATCH (c:Class) WHERE c.name = '{class_name}' RETURN c.id LIMIT 1"
                )
                if cls_rows:
                    store.create_edge(
                        "CONTRACT_DECLARES_CLASS",
                        "Contract",
                        contract_id,
                        "Class",
                        cls_rows[0]["c.id"],
                    )
                    declares_edge_count += 1

    # --- Learnings ---
    if learnings_file.is_file():
        for lr in _parse_learnings(learnings_file):
            lr_id = f"learning::{lr['learning_id']}"
            store.create_node(
                "Learning",
                {
                    "id": lr_id,
                    "learningId": lr["learning_id"],
                    "planNumber": lr["plan_number"],
                    "description": lr["description"],
                    "target": lr["target"],
                    "status": lr["status"],
                },
            )
            learning_count += 1

            # Link learning to its source plan
            plan_id = f"plan::{lr['plan_number']}"
            # We only link if the plan node exists (best effort)

            # Link learning to referenced files via target field
            target = lr["target"]
            for fpath, fid in file_id_map.items():
                if fpath in target or Path(fpath).stem in target:
                    store.create_edge(
                        "LEARNING_RELATES_TO_FILE",
                        "Learning",
                        lr_id,
                        "File",
                        fid,
                    )

    return {
        "plans": plan_count,
        "contracts": contract_count,
        "learnings": learning_count,
        "findings": finding_count,
        "impact_edges": impact_edge_count,
    }
