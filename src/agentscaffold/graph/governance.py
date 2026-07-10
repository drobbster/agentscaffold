"""Phase 4: Governance artifact ingestion.

Parses markdown-based governance artifacts (plans, contracts, learnings,
review findings, studies, ADRs, spikes) and creates corresponding graph
nodes and edges.

Artifacts follow AgentScaffold template conventions:
- Plans:     docs/ai/plans/plan_NNN_*.md
- Contracts: docs/ai/contracts/*.md
- Learnings: docs/ai/state/learnings_tracker.md
- Studies:   docs/studies/STU-*.md (YAML frontmatter)
- ADRs:      docs/ai/adrs/*.md (heading-based metadata)
- Spikes:    docs/ai/spikes/*.md (heading/table metadata)
- Findings:  embedded in plan appendices or standalone review files
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from agentscaffold.graph.query_compat import ql, sql_escape

if TYPE_CHECKING:
    from agentscaffold.graph.backend import GraphBackend

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

_PLAN_METADATA_RE = re.compile(
    r"^\|\s*(?P<key>[^|]+?)\s*\|\s*(?P<value>[^|]+?)\s*\|",
    re.MULTILINE,
)
_PLAN_NUMBER_RE = re.compile(r"^(?:plan[_\-]?)?0*(\d+)", re.IGNORECASE)
_FILE_IMPACT_ROW_RE = re.compile(
    r"^\|\s*(?!File\s|---)[`]?(?P<path>[^|`]+?)[`]?\s*\|" r"\s*(?P<change_type>[^|]+?)\s*\|",
    re.MULTILINE,
)
_HEADER_VALUES = {"File", "Change Type", "Description", "---"}


def _extract_plan_number(filename: str) -> int | None:
    """Extract the plan number from plan_042_foo.md or 042-foo.md style filenames."""
    m = _PLAN_NUMBER_RE.search(filename)
    return int(m.group(1)) if m else None


_PLAN_LIST_META_RE = re.compile(
    r"^\s*-\s+(?P<key>[^:]+?):\s*(?P<value>.+)",
    re.MULTILINE,
)

_PLAN_STATUS_HEADING_RE = re.compile(
    r"^##\s+(?:STATUS|Status):\s*(?P<status>.+)",
    re.MULTILINE,
)


def _extract_metadata(text: str) -> dict[str, str]:
    """Extract key-value metadata from table rows, list items, or status headings."""
    meta: dict[str, str] = {}
    header = text[:4000]

    # Table format: | Key | Value |
    for m in _PLAN_METADATA_RE.finditer(header):
        key = m.group("key").strip().lower().replace(" ", "_")
        value = m.group("value").strip()
        if key and value and value != "---":
            meta[key] = value

    # List format: - Key: Value
    for m in _PLAN_LIST_META_RE.finditer(header):
        key = m.group("key").strip().lower().replace(" ", "_")
        value = m.group("value").strip()
        if key and value:
            meta.setdefault(key, value)

    # Status heading: ## STATUS: Complete
    sm = _PLAN_STATUS_HEADING_RE.search(header)
    if sm:
        meta.setdefault("status", sm.group("status").strip())

    return meta


_FILE_IMPACT_HEADING_RE = re.compile(
    r"^##\s+(?:\d+\.\s+)?File\s+Impact\s+Map",
    re.MULTILINE | re.IGNORECASE,
)


def _extract_file_impact(text: str) -> list[dict[str, str]]:
    """Extract files from the File Impact Map table."""
    impacts: list[dict[str, str]] = []
    heading_match = _FILE_IMPACT_HEADING_RE.search(text)
    if not heading_match:
        return impacts
    section_start = heading_match.start()

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

    dependencies = _extract_dependencies(meta)

    return {
        "number": number,
        "title": title,
        "status": status,
        "plan_type": plan_type,
        "filepath": str(filepath),
        "created": created,
        "last_updated": last_updated,
        "file_impacts": impacts,
        "dependencies": dependencies,
        "text": text,
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

# 5-column table: | ID | Plan | Description | Target | Status |
_LEARNING_RE_5COL = re.compile(
    r"^\|\s*(?P<id>L\d+-\d+)\s*\|"
    r"\s*(?P<plan>\d+)\s*\|"
    r"\s*(?P<desc>[^|]+?)\s*\|"
    r"\s*(?P<target>[^|]+?)\s*\|"
    r"\s*(?P<status>[^|]+?)\s*\|",
    re.MULTILINE,
)

# 4-column table: | ID | Learning | Target | Status | (plan number in ID)
_LEARNING_RE_4COL = re.compile(
    r"^\|\s*(?P<id>L(?P<plan>\d+)-\d+)\s*\|"
    r"\s*(?P<desc>[^|]+?)\s*\|"
    r"\s*(?P<target>[^|]+?)\s*\|"
    r"\s*(?P<status>[^|]+?)\s*\|",
    re.MULTILINE,
)

# 3-column table: | ID | Learning | Target | (no status, plan in ID)
_LEARNING_RE_3COL = re.compile(
    r"^\|\s*(?P<id>L(?P<plan>\d+)-\d+)\s*\|"
    r"\s*(?P<desc>[^|]+?)\s*\|"
    r"\s*(?P<target>[^|]+?)\s*\|\s*$",
    re.MULTILINE,
)

# YAML-like list: ### L042-1 / - Plan: 042 / - Description: ... / - Target: ... / - Status: ...
_LEARNING_RE_LIST = re.compile(
    r"^###\s+(?P<id>L(?P<plan>\d+)-\d+)\s*\n"
    r"(?:-\s*Plan:\s*\d+\s*\n)?"
    r"-\s*Description:\s*(?P<desc>.+?)\s*\n"
    r"-\s*Target:\s*(?P<target>.+?)\s*\n"
    r"-\s*Status:\s*(?P<status>\S+)",
    re.MULTILINE,
)


def _parse_learnings(filepath: Path) -> list[dict[str, Any]]:
    """Parse the learnings tracker in any of the supported formats.

    Supports three formats:
    - 5-column table: ``| ID | Plan | Description | Target | Status |``
    - 4-column table: ``| ID | Learning | Target | Status |`` (plan in ID)
    - YAML-like list:  ``### L042-1`` with ``- Plan:`` / ``- Description:`` fields
    """
    try:
        text = filepath.read_text(errors="replace")
    except OSError:
        return []

    learnings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for regex in (_LEARNING_RE_5COL, _LEARNING_RE_4COL, _LEARNING_RE_3COL, _LEARNING_RE_LIST):
        for m in regex.finditer(text):
            learning_id = m.group("id").strip()
            if learning_id in seen_ids:
                continue
            seen_ids.add(learning_id)
            plan_number = int(m.group("plan").strip())
            description = m.group("desc").strip()
            target = m.group("target").strip()
            try:
                status = m.group("status").strip()
            except IndexError:
                status = "Pending"
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

# Categories emitted by the review engine (challenges.py + gaps.py) plus the
# manual categories used in hand-written review appendices. Order matters:
# categories that are prefixes of others (CONSUMER, DEPENDENCY, PATTERN) must
# come AFTER their longer variants so the alternation prefers the longest match.
# The optional (?P<severity>!{1,2}) consumes the "!"/"!!" severity markers the
# formatters append (e.g. "[DEPENDENCY]!! ..."), keeping them out of the text.
_FINDING_RE = re.compile(
    r"\[(?P<category>"
    r"DEPENDENCY_COMPLETENESS|DEPENDENCY|"
    r"CONSUMER_AUDIT|CONSUMER|"
    r"SIMILAR_PATTERN|PATTERN|"
    r"INTEGRATION_POINTS|TEST_COVERAGE|"
    r"HISTORY|LEARNING|LAYER|CONTRACT|PERFORMANCE|"
    r"FINDING|RISK|GAP|EDGE_CASE"
    r")\](?P<severity>!{1,2})?\s*(?P<text>[^\n]+(?:\n(?!\[)[^\n]+)*)",
    re.MULTILINE,
)

# Map the formatter's severity markers to ReviewFinding severity levels.
_SEVERITY_BY_MARKER = {"!!": "high", "!": "medium", "": "medium"}


def _parse_review_findings(text: str, plan_number: int, review_type: str) -> list[dict[str, Any]]:
    """Extract structured review findings from review text."""
    findings: list[dict[str, Any]] = []
    for i, m in enumerate(_FINDING_RE.finditer(text)):
        severity = _SEVERITY_BY_MARKER.get(m.group("severity") or "", "medium")
        findings.append(
            {
                "plan_number": plan_number,
                "review_type": review_type,
                "category": m.group("category").strip(),
                "finding": m.group("text").strip()[:500],
                "severity": severity,
                "resolution": "",
                "status": "open",
                "index": i,
            }
        )
    return findings


# Review type label for findings ingested from plan-file text at index time,
# distinguishing them from runtime write-back findings ("pre_review", etc.).
_PLAN_APPENDIX_REVIEW_TYPE = "plan_appendix"


def _ingest_plan_findings(store: GraphBackend, plan_number: int, text: str) -> int:
    """Create ReviewFinding nodes from [CATEGORY] markers in a plan's text.

    Returns the number of findings parsed. Nodes use deterministic ids and
    create_node's ON CONFLICT DO NOTHING semantics, so this is idempotent
    across re-indexing and never clobbers a finding already marked resolved.
    """
    from agentscaffold.graph.findings import _finding_id

    raw = _parse_review_findings(text, plan_number, _PLAN_APPENDIX_REVIEW_TYPE)
    for f in raw:
        finding_id = _finding_id(
            plan_number, _PLAN_APPENDIX_REVIEW_TYPE, f["category"], f["finding"]
        )
        store.create_node(
            "ReviewFinding",
            {
                "id": finding_id,
                "reviewType": _PLAN_APPENDIX_REVIEW_TYPE,
                "planNumber": plan_number,
                "severity": f["severity"],
                "category": f["category"],
                "finding": f["finding"],
                "resolution": "",
                "status": "open",
            },
        )
    return len(raw)


# ---------------------------------------------------------------------------
# Study parsing (YAML frontmatter)
# ---------------------------------------------------------------------------

_STUDY_SKIP_FILES = {"README.md", "study_template.md"}


def _parse_study(filepath: Path) -> dict[str, Any] | None:
    """Parse a study file with YAML frontmatter between --- markers."""
    try:
        text = filepath.read_text(errors="replace")
    except OSError:
        return None

    if not text.startswith("---"):
        return None

    end = text.find("---", 3)
    if end == -1:
        return None

    try:
        fm = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        logger.debug("Failed to parse YAML frontmatter in %s", filepath)
        return None

    if not isinstance(fm, dict):
        return None

    study_id = fm.get("study_id", "")
    if not study_id:
        return None

    artifacts = fm.get("artifacts") or []
    artifact_paths: list[str] = []
    if isinstance(artifacts, list):
        for a in artifacts:
            if isinstance(a, dict) and a.get("path"):
                artifact_paths.append(a["path"])

    tags = fm.get("tags") or []
    related_plans = fm.get("related_plans") or []

    return {
        "study_id": study_id,
        "title": fm.get("title", ""),
        "study_type": fm.get("study_type", ""),
        "status": fm.get("status", "unknown"),
        "outcome": fm.get("outcome") or "",
        "confidence": fm.get("confidence") or "",
        "tags": ",".join(str(t) for t in tags) if isinstance(tags, list) else str(tags),
        "related_plans": [int(p) for p in related_plans if str(p).isdigit()],
        "filepath": str(filepath),
        "started": str(fm.get("started", "")),
        "completed": str(fm.get("completed") or ""),
        "artifact_paths": artifact_paths,
    }


# ---------------------------------------------------------------------------
# ADR parsing (markdown heading-based)
# ---------------------------------------------------------------------------

_ADR_TITLE_RE = re.compile(r"^#\s+ADR-(\d+):\s*(.+)", re.MULTILINE)
_ADR_NUMBER_RE = re.compile(r"^(?:adr[_\-]?)?0*(\d+)", re.IGNORECASE)
_ADR_SKIP_FILES = {"README.md", "adr_template.md"}

_SUPERSEDED_RE = re.compile(r"Superseded\s+by\s+ADR-(\d+)", re.IGNORECASE)
_RELATED_PLANS_RE = re.compile(
    r"Related\s+Plans?:\s*(.+)",
    re.IGNORECASE,
)
_RELATED_ADRS_RE = re.compile(
    r"Related\s+ADRs?:\s*(.+)",
    re.IGNORECASE,
)
_STUDY_REF_RE = re.compile(r"STU-\d{4}-\d{2}-\d{2}-[\w-]+")
_SPIKE_REF_RE = re.compile(r"[Ss]pike[\s\-:]+(.+?)(?:\n|$)")


def _extract_section_text(text: str, heading: str) -> str:
    """Return the text under a ## heading until the next ## heading."""
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE | re.IGNORECASE)
    m = pattern.search(text)
    if not m:
        return ""
    start = m.end()
    next_heading = re.search(r"^## ", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def _parse_adr(filepath: Path) -> dict[str, Any] | None:
    """Parse an ADR markdown file using heading-based metadata."""
    try:
        text = filepath.read_text(errors="replace")
    except OSError:
        return None

    # Extract number from title line or filename
    title_m = _ADR_TITLE_RE.search(text)
    if title_m:
        number = int(title_m.group(1))
        title = title_m.group(2).strip()
    else:
        num_m = _ADR_NUMBER_RE.search(filepath.stem)
        if not num_m:
            return None
        number = int(num_m.group(1))
        h1 = re.search(r"^#\s+(.+)", text, re.MULTILINE)
        title = h1.group(1).strip() if h1 else filepath.stem

    status_text = _extract_section_text(text, "Status")
    status_line = status_text.split("\n")[0].strip() if status_text else "unknown"

    date_text = _extract_section_text(text, "Date")
    date_line = date_text.split("\n")[0].strip() if date_text else ""

    related_section = _extract_section_text(text, "Related")

    related_plans_str = ""
    rp_m = _RELATED_PLANS_RE.search(related_section)
    if rp_m:
        related_plans_str = rp_m.group(1).strip()

    related_adrs_str = ""
    ra_m = _RELATED_ADRS_RE.search(related_section)
    if ra_m:
        related_adrs_str = ra_m.group(1).strip()

    superseded_by = ""
    sup_m = _SUPERSEDED_RE.search(status_line)
    if sup_m:
        superseded_by = sup_m.group(1)

    # Extract plan numbers from related_plans_str (e.g. "Plan 005, Plan 087")
    plan_numbers: list[int] = []
    for pm in re.finditer(r"(?:Plan\s+)?(\d+)", related_plans_str):
        plan_numbers.append(int(pm.group(1)))

    # Extract ADR numbers from related_adrs_str
    adr_numbers: list[int] = []
    for am in re.finditer(r"(?:ADR-?)(\d+)", related_adrs_str):
        adr_numbers.append(int(am.group(1)))

    # Extract study references from Supporting Evidence
    evidence_section = _extract_section_text(text, "Supporting Evidence")
    cited_studies = _STUDY_REF_RE.findall(evidence_section)

    return {
        "number": number,
        "title": title,
        "status": status_line,
        "date": date_line,
        "filepath": str(filepath),
        "related_plans": plan_numbers,
        "related_adrs": adr_numbers,
        "superseded_by": superseded_by,
        "cited_studies": cited_studies,
    }


# ---------------------------------------------------------------------------
# Spike parsing (heading/table metadata)
# ---------------------------------------------------------------------------

_SPIKE_TITLE_RE = re.compile(r"^#\s+Spike:\s*(.+)", re.MULTILINE)
_SPIKE_SKIP_FILES = {"spike_template.md"}
_SPIKE_TABLE_RE = re.compile(
    r"^\|\s*(?P<key>[^|]+?)\s*\|\s*(?P<value>[^|]+?)\s*\|",
    re.MULTILINE,
)
_SPIKE_PLAN_RE = re.compile(r"(?:Plan\s+)?(\d+)", re.IGNORECASE)


def _parse_spike(filepath: Path) -> dict[str, Any] | None:
    """Parse a spike markdown file using heading or table metadata."""
    try:
        text = filepath.read_text(errors="replace")
    except OSError:
        return None

    title_m = _SPIKE_TITLE_RE.search(text)
    title = title_m.group(1).strip() if title_m else filepath.stem

    # Try table metadata first (most common format)
    meta: dict[str, str] = {}
    for m in _SPIKE_TABLE_RE.finditer(text[:2000]):
        key = m.group("key").strip().lower().replace(" ", "_")
        value = m.group("value").strip()
        if key and value and value != "---" and key not in ("field", "---"):
            meta[key] = value

    parent_plan = ""
    plan_num_str = meta.get("parent_plan", "")
    if not plan_num_str:
        pp_section = _extract_section_text(text, "Parent Plan")
        plan_num_str = pp_section.split("\n")[0].strip() if pp_section else ""

    pp_m = _SPIKE_PLAN_RE.search(plan_num_str) if plan_num_str else None
    if pp_m:
        parent_plan = pp_m.group(1)

    status = meta.get("status", "")
    if not status:
        status_section = _extract_section_text(text, "Status")
        status = status_section.split("\n")[0].strip() if status_section else "unknown"

    created = meta.get("created", "")
    time_box = meta.get("time-box", meta.get("time_box", ""))

    return {
        "title": title,
        "parent_plan": parent_plan,
        "status": status,
        "created": created,
        "filepath": str(filepath),
        "time_box": time_box,
    }


# ---------------------------------------------------------------------------
# Plan dependency extraction
# ---------------------------------------------------------------------------

_DEPENDENCY_RE = re.compile(
    r"(?:Plan\s+)?(\d{2,})",
)


def _extract_dependencies(meta: dict[str, str]) -> list[int]:
    """Extract plan dependency numbers from metadata."""
    dep_str = meta.get("dependencies", "")
    if not dep_str or dep_str.lower() in ("none", "n/a", "---"):
        return []
    return [int(m.group(1)) for m in _DEPENDENCY_RE.finditer(dep_str)]


# ---------------------------------------------------------------------------
# Pipeline phase: ingest governance artifacts
# ---------------------------------------------------------------------------


def governance_source_files(root: Path, config: Any | None = None) -> list[Path]:
    """Return all governance source files that ``process_governance`` ingests.

    Used by the incremental indexer to fingerprint governance state and decide
    whether a governance refresh is needed (doc-only edits that the code
    changeset cannot see). Mirrors the directory resolution in
    ``process_governance`` so the two stay in sync.
    """
    if config and hasattr(config, "graph"):
        gc = config.graph
        dirs = [
            root / gc.plans_dir,
            root / gc.contracts_dir,
            root / gc.studies_dir,
            root / gc.adrs_dir,
            root / gc.spikes_dir,
        ]
        files = [
            root / gc.learnings_file,
            root / gc.backlog_file,
            root / gc.backlog_archive_file,
            root / gc.governance_artifact,
            root / getattr(gc, "architecture_doc", "docs/ai/system_architecture.md"),
        ]
    else:
        dirs = [
            root / "docs" / "ai" / "plans",
            root / "docs" / "ai" / "contracts",
            root / "docs" / "studies",
            root / "docs" / "ai" / "adrs",
            root / "docs" / "ai" / "spikes",
        ]
        files = [
            root / "docs" / "ai" / "state" / "learnings_tracker.md",
            root / "docs" / "ai" / "backlog.md",
            root / "docs" / "ai" / "backlog_archive.md",
            root / "docs" / "ai" / "state" / "governance.json",
            root / "docs" / "ai" / "system_architecture.md",
        ]

    result: list[Path] = []
    for d in dirs:
        if d.is_dir():
            result.extend(sorted(d.rglob("*.md")))
    for f in files:
        if f.is_file():
            result.append(f)
    return result


def _ingest_architecture_layers(
    store: GraphBackend,
    architecture_doc: Path,
    file_id_map: dict[str, str],
) -> tuple[int, int]:
    """Ingest ArchitectureLayer nodes and BELONGS_TO_LAYER edges.

    Returns ``(layer_count, edge_count)``. A missing doc or a doc with only
    placeholder layers is a no-op that returns ``(0, 0)``.
    """
    from agentscaffold.graph.architecture import (
        match_layer_for_file,
        parse_architecture_layers,
    )

    if not architecture_doc.is_file():
        return (0, 0)

    layers = parse_architecture_layers(architecture_doc.read_text(errors="replace"))
    if not layers:
        return (0, 0)

    for layer in layers:
        store.create_node(
            "ArchitectureLayer",
            {
                "id": f"layer::{layer.number}",
                "number": layer.number,
                "name": layer.name,
                "description": layer.description,
                "pathPatterns": ",".join(layer.path_patterns),
            },
        )

    edge_count = 0
    # Only layers that actually declare patterns can own files.
    mappable = [layer for layer in layers if layer.path_patterns]
    if mappable:
        for path, file_id in file_id_map.items():
            layer = match_layer_for_file(path, mappable)
            if layer is not None:
                store.create_edge(
                    "BELONGS_TO_LAYER",
                    "File",
                    file_id,
                    "ArchitectureLayer",
                    f"layer::{layer.number}",
                )
                edge_count += 1
    return (len(layers), edge_count)


def process_governance(
    store: GraphBackend,
    root: Path,
    config: Any | None = None,
) -> dict[str, Any]:
    """Ingest governance artifacts into the graph.

    Scans standard AgentScaffold directories for plans, contracts,
    learnings, studies, ADRs, spikes, and review findings.

    Returns summary with counts.
    """
    # Resolve directories from config or use defaults
    if config and hasattr(config, "graph"):
        gc = config.graph
        plans_dir = root / gc.plans_dir
        contracts_dir = root / gc.contracts_dir
        learnings_file = root / gc.learnings_file
        studies_dir = root / gc.studies_dir
        adrs_dir = root / gc.adrs_dir
        spikes_dir = root / gc.spikes_dir
        architecture_doc = root / getattr(gc, "architecture_doc", "docs/ai/system_architecture.md")
    else:
        plans_dir = root / "docs" / "ai" / "plans"
        contracts_dir = root / "docs" / "ai" / "contracts"
        learnings_file = root / "docs" / "ai" / "state" / "learnings_tracker.md"
        studies_dir = root / "docs" / "studies"
        adrs_dir = root / "docs" / "ai" / "adrs"
        spikes_dir = root / "docs" / "ai" / "spikes"
        architecture_doc = root / "docs" / "ai" / "system_architecture.md"

    # Restore git-backed governance (Plan 222): findings, sessions, and backlog
    # items recorded at runtime live in a committed artifact, not in code. On a
    # fresh build the graph has none of them, so ingest the artifact (idempotent)
    # before parsing code-derived governance. A missing artifact is a no-op; a
    # corrupt one is logged and skipped so indexing still completes.
    governance_restored: dict[str, Any] = {}
    try:
        from agentscaffold.graph.governance_store import (
            ingest_governance,
            resolve_governance_artifact,
        )

        artifact_path = resolve_governance_artifact(config, start=root)
        governance_restored = ingest_governance(store, artifact_path)
    except Exception as exc:  # noqa: BLE001 - artifact restore must not break indexing
        logger.warning("Governance artifact restore failed: %s", exc)

    plan_count = 0
    contract_count = 0
    learning_count = 0
    finding_count = 0
    impact_edge_count = 0
    study_count = 0
    adr_count = 0
    spike_count = 0
    layer_count = 0
    layer_edge_count = 0

    # File ID lookup for linking governance -> code nodes
    file_id_map: dict[str, str] = {}
    for row in ql(
        store,
        sql='SELECT id AS "f.id", path AS "f.path" FROM File',
    ):
        file_id_map[row["f.path"]] = row["f.id"]

    # --- Architecture layers (Plan 237) ---
    # Parse the human-owned architecture baseline into ArchitectureLayer nodes and
    # link each file to its most-specific layer. A missing/placeholder doc yields
    # no layers (clean no-op); a parse failure is logged and skipped so indexing
    # still completes, mirroring the governance-artifact restore contract.
    try:
        layer_count, layer_edge_count = _ingest_architecture_layers(
            store, architecture_doc, file_id_map
        )
    except Exception as exc:  # noqa: BLE001 - layer ingestion must not break indexing
        logger.warning("Architecture layer ingestion failed: %s", exc)

    # Track plan number -> plan_id for cross-referencing
    plan_number_to_id: dict[int, str] = {}

    # --- Plans ---
    plan_dependencies: list[tuple[str, list[int]]] = []
    if plans_dir.is_dir():
        seen_plan_ids: set[str] = set()
        for plan_file in sorted(plans_dir.glob("*.md")):
            data = _parse_plan(plan_file)
            if data is None:
                continue

            plan_id = f"plan::{data['number']}"
            if plan_id in seen_plan_ids:
                plan_id = f"plan::{data['number']}::{plan_file.stem}"
            seen_plan_ids.add(plan_id)
            plan_number_to_id[data["number"]] = plan_id

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

            if data.get("dependencies"):
                plan_dependencies.append((plan_id, data["dependencies"]))

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

            # Ingest review findings embedded as [CATEGORY] markers in the plan
            # text (e.g. pasted review/retro output). Idempotent: ReviewFinding
            # ids are deterministic and create_node is ON CONFLICT DO NOTHING, so
            # re-indexing re-affirms findings and preserves any 'resolved' status
            # set later via the runtime resolve_finding path.
            finding_count += _ingest_plan_findings(store, data["number"], data["text"])

    # --- Plan dependency edges (second pass, all plan nodes exist) ---
    dep_edge_count = 0
    for plan_id, dep_numbers in plan_dependencies:
        for dep_num in dep_numbers:
            dep_id = plan_number_to_id.get(dep_num)
            if dep_id:
                store.create_edge("DEPENDS_ON_PLAN", "Plan", plan_id, "Plan", dep_id)
                dep_edge_count += 1

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

            # Files that contain a declared symbol -> direct CONTRACT_ABOUT_FILE
            # edge (Plan 237). This makes contract coverage a first-class,
            # queryable relationship instead of only an implicit declares-join.
            contract_files: set[str] = set()

            for method_name in data.get("declared_methods", []):
                fn_rows = ql(
                    store,
                    sql=(
                        'SELECT id AS "fn.id", filePath AS "fn.filePath"'
                        f" FROM Function WHERE name = '{sql_escape(method_name)}' LIMIT 1"
                    ),
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
                    fpath = fn_rows[0].get("fn.filePath")
                    if fpath:
                        contract_files.add(fpath)

            for class_name in data.get("declared_classes", []):
                cls_rows = ql(
                    store,
                    sql=(
                        'SELECT id AS "c.id", filePath AS "c.filePath"'
                        f" FROM Class WHERE name = '{sql_escape(class_name)}' LIMIT 1"
                    ),
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
                    fpath = cls_rows[0].get("c.filePath")
                    if fpath:
                        contract_files.add(fpath)

            for fpath in contract_files:
                file_id = file_id_map.get(fpath)
                if file_id:
                    store.create_edge(
                        "CONTRACT_ABOUT_FILE",
                        "Contract",
                        contract_id,
                        "File",
                        file_id,
                    )

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

    # --- Studies ---
    study_id_map: dict[str, str] = {}
    if studies_dir.is_dir():
        for study_file in sorted(studies_dir.glob("*.md")):
            if study_file.name in _STUDY_SKIP_FILES:
                continue
            data = _parse_study(study_file)
            if data is None:
                continue

            sid = f"study::{data['study_id']}"
            study_id_map[data["study_id"]] = sid
            store.create_node(
                "Study",
                {
                    "id": sid,
                    "studyId": data["study_id"],
                    "title": data["title"],
                    "studyType": data["study_type"],
                    "status": data["status"],
                    "outcome": data["outcome"],
                    "confidence": data["confidence"],
                    "tags": data["tags"],
                    "relatedPlans": ",".join(str(p) for p in data["related_plans"]),
                    "filePath": data["filepath"],
                    "started": data["started"],
                    "completed": data["completed"],
                },
            )
            study_count += 1

            for plan_num in data["related_plans"]:
                pid = plan_number_to_id.get(plan_num)
                if pid:
                    store.create_edge("STUDY_REFERENCES_PLAN", "Study", sid, "Plan", pid)

            for apath in data["artifact_paths"]:
                if apath in file_id_map:
                    store.create_edge(
                        "STUDY_REFERENCES_FILE", "Study", sid, "File", file_id_map[apath]
                    )

    # --- Spikes ---
    spike_id_map: dict[str, str] = {}
    if spikes_dir.is_dir():
        for spike_file in sorted(spikes_dir.glob("*.md")):
            if spike_file.name in _SPIKE_SKIP_FILES:
                continue
            data = _parse_spike(spike_file)
            if data is None:
                continue

            spk_id = f"spike::{spike_file.stem}"
            spike_id_map[spike_file.stem] = spk_id
            store.create_node(
                "Spike",
                {
                    "id": spk_id,
                    "title": data["title"],
                    "parentPlan": data["parent_plan"],
                    "status": data["status"],
                    "created": data["created"],
                    "filePath": data["filepath"],
                    "timeBox": data["time_box"],
                },
            )
            spike_count += 1

            if data["parent_plan"]:
                pid = plan_number_to_id.get(int(data["parent_plan"]))
                if pid:
                    store.create_edge("SPIKE_FOR_PLAN", "Spike", spk_id, "Plan", pid)

    # --- ADRs ---
    adr_id_map: dict[int, str] = {}
    seen_adr_ids: set[str] = set()
    adr_edges_deferred: list[dict[str, Any]] = []
    if adrs_dir.is_dir():
        for adr_file in sorted(adrs_dir.glob("*.md")):
            if adr_file.name in _ADR_SKIP_FILES:
                continue
            data = _parse_adr(adr_file)
            if data is None:
                continue

            aid = f"adr::{data['number']}"
            if aid in seen_adr_ids:
                aid = f"adr::{data['number']}::{adr_file.stem}"
            seen_adr_ids.add(aid)
            adr_id_map.setdefault(data["number"], aid)
            store.create_node(
                "ADR",
                {
                    "id": aid,
                    "number": data["number"],
                    "title": data["title"],
                    "status": data["status"],
                    "date": data["date"],
                    "filePath": data["filepath"],
                    "relatedPlans": ",".join(str(p) for p in data["related_plans"]),
                    "relatedADRs": ",".join(str(a) for a in data["related_adrs"]),
                    "supersededBy": data["superseded_by"],
                },
            )
            adr_count += 1

            for plan_num in data["related_plans"]:
                pid = plan_number_to_id.get(plan_num)
                if pid:
                    store.create_edge("ADR_GOVERNS", "ADR", aid, "Plan", pid)

            adr_edges_deferred.append(
                {
                    "adr_id": aid,
                    "adr_number": data["number"],
                    "superseded_by": data["superseded_by"],
                    "cited_studies": data.get("cited_studies", []),
                }
            )

    # --- ADR cross-reference edges (second pass, all ADR/Study/Spike nodes exist) ---
    for item in adr_edges_deferred:
        aid = item["adr_id"]
        if item["superseded_by"]:
            try:
                sup_num = int(item["superseded_by"])
                sup_id = adr_id_map.get(sup_num)
                if sup_id:
                    store.create_edge("ADR_SUPERSEDES", "ADR", aid, "ADR", sup_id)
            except ValueError:
                pass

        for study_ref in item["cited_studies"]:
            study_node_id = study_id_map.get(study_ref)
            if study_node_id:
                store.create_edge("ADR_CITES_STUDY", "ADR", aid, "Study", study_node_id)

    logger.info(
        "Governance: %d plans, %d contracts, %d learnings, %d studies, %d ADRs, %d spikes, "
        "%d layers, %d impact edges, %d dep edges, %d layer edges",
        plan_count,
        contract_count,
        learning_count,
        study_count,
        adr_count,
        spike_count,
        layer_count,
        impact_edge_count,
        dep_edge_count,
        layer_edge_count,
    )

    return {
        "plans": plan_count,
        "contracts": contract_count,
        "learnings": learning_count,
        "findings": finding_count,
        "impact_edges": impact_edge_count,
        "studies": study_count,
        "adrs": adr_count,
        "spikes": spike_count,
        "layers": layer_count,
        "layer_edges": layer_edge_count,
        "dependency_edges": dep_edge_count,
        "governance_restored": (
            sum(governance_restored.get("imported", {}).values())
            if governance_restored.get("present")
            else 0
        ),
    }
