"""Code embeddings for semantic similarity search.

Generates vector embeddings for code definitions (functions, classes, methods)
using sentence-transformers. Embeddings are stored in the EmbeddingStore table
and support cosine similarity search via DuckDB's list_cosine_similarity.

Requires: pip install agentscaffold[search]
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from agentscaffold.graph.backend import GraphBackend

logger = logging.getLogger(__name__)

try:
    import os as _os
    import warnings as _warnings

    _os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    _os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")
        _hf_logger = logging.getLogger("sentence_transformers")
        _hf_logger.setLevel(logging.WARNING)
        logging.getLogger("transformers").setLevel(logging.WARNING)
        from sentence_transformers import SentenceTransformer

    _st_available = True
except ImportError:
    _st_available = False

DEFAULT_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
# Cache keyed by (model_name, resolved_cache_dir) so a pinned cache dir does not
# collide with the default Hugging Face cache.
_model_cache: dict[tuple[str, str | None], Any] = {}

# Upper bound on resident models (Plan 249, Step A7c). Step A7c removed the
# reason this grew with project count -- the default cache dir is now shared, so
# N projects produce one key rather than N. This bound is defence in depth for
# genuinely distinct models, and it is safe in a way the graph handle pool's
# ceiling was not: dropping a model from this dict does not invalidate a
# reference a caller already holds, whereas closing a DuckDB connection breaks an
# in-flight reader. So a plain bound suffices here; no lease or refcount.
MAX_CACHED_MODELS = 4


def _remember_model(key: tuple[str, str | None], model: Any) -> Any:
    """Store *model* under *key*, evicting the oldest entry past the bound."""
    _model_cache[key] = model
    while len(_model_cache) > MAX_CACHED_MODELS:
        _model_cache.pop(next(iter(_model_cache)))
    return model


# Process-wide embedding configuration (Plan 227, Tier 2a). Set once from
# ``scaffold.yaml`` via ``configure_embeddings`` at a CLI/MCP entrypoint; all
# embedding/search code then loads the same model from the same pinned cache,
# so indexing and querying agree and provisioning is deterministic/offline.
_configured_model_name: str = DEFAULT_MODEL
_configured_cache_dir: str | None = None


def _resolve_cache_dir(cache_dir: str | None) -> str | None:
    """Resolve a weights cache dir, sharing the shipped default across projects.

    Delegates to :func:`agentscaffold.paths.resolve_model_cache_dir` so there is
    one rule rather than two. Before Plan 249 Step A7c this resolved relative
    paths against the project root unconditionally, which meant the default
    ``.scaffold/models`` gave every project its own copy of identical weights.
    """
    if not cache_dir:
        return None
    from pathlib import Path

    try:
        from agentscaffold.config import ScaffoldConfig, SearchConfig
        from agentscaffold.paths import resolve_model_cache_dir

        resolved = resolve_model_cache_dir(ScaffoldConfig(search=SearchConfig(cache_dir=cache_dir)))
        return str(resolved) if resolved is not None else None
    except Exception:
        # Path policy must never be the reason search fails to start.
        path = Path(cache_dir)
        return str(path if path.is_absolute() else path.resolve())


def configure_embeddings(model_name: str | None = None, cache_dir: str | None = None) -> None:
    """Set the process-wide embedding model + pinned weights cache (Plan 227).

    Call once from a CLI/MCP entrypoint after loading ``scaffold.yaml``. Passing
    ``None`` leaves the current value unchanged for ``model_name`` and clears the
    pin for ``cache_dir`` only when explicitly asked.
    """
    global _configured_model_name, _configured_cache_dir
    if model_name:
        _configured_model_name = model_name
    _configured_cache_dir = _resolve_cache_dir(cache_dir)


def _active_model_name(model_name: str | None = None) -> str:
    return model_name or _configured_model_name


def _active_cache_dir(cache_dir: str | None = None) -> str | None:
    return _resolve_cache_dir(cache_dir) if cache_dir else _configured_cache_dir


def _get_model(model_name: str | None = None, cache_dir: str | None = None) -> Any:
    """Load and cache a SentenceTransformer model, suppressing noisy output.

    Honors the pinned weights cache dir (``configure_embeddings`` / explicit
    ``cache_dir``) so the model resolves from a deterministic, offline-capable
    location.
    """
    name = _active_model_name(model_name)
    cdir = _active_cache_dir(cache_dir)
    key = (name, cdir)
    if key in _model_cache:
        return _model_cache[key]

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _prev_level = logging.root.level
        logging.disable(logging.WARNING)
        try:
            model = SentenceTransformer(name, cache_folder=cdir)
        finally:
            logging.disable(logging.NOTSET)
            logging.root.setLevel(_prev_level)

    return _remember_model(key, model)


def warm_model(model_name: str | None = None, cache_dir: str | None = None) -> str:
    """Download + cache the embedding model so later loads are offline/instant.

    This is the deliberate provisioning step: installing the ``[search]`` extra
    gets the *library* but not the model *weights*, which sentence-transformers
    otherwise downloads lazily on first use (a runtime failure offline). Returns
    the resolved model name.

    Raises ImportError (with an actionable message) if ``[search]`` is absent.
    """
    if not _st_available:
        raise ImportError(
            "Model provisioning requires sentence-transformers: pip install 'agentscaffold[search]'"
        )
    _get_model(model_name, cache_dir)
    return _active_model_name(model_name)


def model_ready(model_name: str | None = None, cache_dir: str | None = None) -> bool:
    """Return True if the model can load offline (package present + weights cached).

    Fast filesystem probe of the Hugging Face cache -- it does not trigger a
    download or a full model load, so it is safe to call on the search hot path
    and in ``scaffold graph model-status``.
    """
    if not _st_available:
        return False
    name = _active_model_name(model_name)
    cdir = _active_cache_dir(cache_dir)
    if (name, cdir) in _model_cache:
        return True
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:
        return False
    repo = name if "/" in name else f"sentence-transformers/{name}"
    try:
        hit = try_to_load_from_cache(repo, "config.json", cache_dir=cdir)
    except Exception:
        return False
    return isinstance(hit, str)


def _ensure_embedding_column(store: GraphBackend, table: str) -> None:
    """Ensure embedding storage is available.

    Embeddings live in the EmbeddingStore auxiliary table (added in schema v4),
    so no ALTER TABLE is required.
    """
    # EmbeddingStore handles storage; no ALTER TABLE needed
    return


def _build_text_for_function(row: dict[str, Any]) -> str:
    """Build a natural-language description of a function for embedding."""
    name = row.get("n.name", "")
    sig = row.get("n.signature", "")
    path = row.get("n.filePath", "")
    parts = [f"function {name}"]
    if sig:
        parts.append(f"signature: {sig}")
    if path:
        module = path.replace("/", ".").removesuffix(".py")
        parts.append(f"in module {module}")
    return " | ".join(parts)


def _build_text_for_class(row: dict[str, Any]) -> str:
    """Build a natural-language description of a class for embedding."""
    name = row.get("n.name", "")
    path = row.get("n.filePath", "")
    parts = [f"class {name}"]
    if path:
        module = path.replace("/", ".").removesuffix(".py")
        parts.append(f"in module {module}")
    return " | ".join(parts)


def _build_text_for_method(row: dict[str, Any]) -> str:
    """Build a natural-language description of a method for embedding."""
    name = row.get("n.name", "")
    cls = row.get("n.className", "")
    sig = row.get("n.signature", "")
    path = row.get("n.filePath", "")
    parts = [f"method {cls}.{name}" if cls else f"method {name}"]
    if sig:
        parts.append(f"signature: {sig}")
    if path:
        module = path.replace("/", ".").removesuffix(".py")
        parts.append(f"in module {module}")
    return " | ".join(parts)


def _build_text_for_file(row: dict[str, Any]) -> str:
    """Build a natural-language description of a file for embedding."""
    path = row.get("n.path", "")
    lang = row.get("n.language", "")
    parts = [f"file {path}"]
    if lang:
        parts.append(f"language: {lang}")
    return " | ".join(parts)


def _nonempty_parts(*parts: Any) -> str:
    return " | ".join(str(p).strip() for p in parts if str(p or "").strip())


def _build_text_for_plan(row: dict[str, Any]) -> str:
    return _nonempty_parts(
        f"plan {row.get('n.number', '')}: {row.get('n.title', '')}",
        f"status: {row.get('n.status', '')}",
        f"type: {row.get('n.planType', '')}",
        f"path: {row.get('n.filePath', '')}",
    )


def _build_text_for_learning(row: dict[str, Any]) -> str:
    return _nonempty_parts(
        f"learning {row.get('n.learningId', row.get('n.id', ''))}",
        row.get("n.description", ""),
        f"target: {row.get('n.target', '')}",
        f"status: {row.get('n.status', '')}",
    )


def _build_text_for_review_finding(row: dict[str, Any]) -> str:
    return _nonempty_parts(
        f"review finding {row.get('n.id', '')}",
        f"severity: {row.get('n.severity', '')}",
        f"category: {row.get('n.category', '')}",
        row.get("n.finding", ""),
        f"resolution: {row.get('n.resolution', '')}",
        f"status: {row.get('n.status', '')}",
    )


def _build_text_for_study(row: dict[str, Any]) -> str:
    return _nonempty_parts(
        f"study {row.get('n.studyId', row.get('n.id', ''))}: {row.get('n.title', '')}",
        f"type: {row.get('n.studyType', '')}",
        f"status: {row.get('n.status', '')}",
        f"outcome: {row.get('n.outcome', '')}",
        f"confidence: {row.get('n.confidence', '')}",
        f"tags: {row.get('n.tags', '')}",
        f"path: {row.get('n.filePath', '')}",
    )


def _build_text_for_adr(row: dict[str, Any]) -> str:
    return _nonempty_parts(
        f"ADR {row.get('n.number', '')}: {row.get('n.title', '')}",
        f"status: {row.get('n.status', '')}",
        f"path: {row.get('n.filePath', '')}",
        f"related plans: {row.get('n.relatedPlans', '')}",
    )


def _build_text_for_spike(row: dict[str, Any]) -> str:
    return _nonempty_parts(
        f"spike {row.get('n.id', '')}: {row.get('n.title', '')}",
        f"parent plan: {row.get('n.parentPlan', '')}",
        f"status: {row.get('n.status', '')}",
        f"path: {row.get('n.filePath', '')}",
    )


def _build_text_for_backlog(row: dict[str, Any]) -> str:
    return _nonempty_parts(
        f"backlog {row.get('n.id', '')}: {row.get('n.title', '')}",
        f"priority: {row.get('n.priority', '')}",
        f"effort: {row.get('n.effort', '')}",
        f"status: {row.get('n.status', '')}",
        f"source: {row.get('n.source', '')}",
    )


_TEXT_BUILDERS = {
    "Function": (_build_text_for_function, "n.name, n.signature, n.filePath"),
    "Class": (_build_text_for_class, "n.name, n.filePath"),
    "Method": (_build_text_for_method, "n.name, n.className, n.signature, n.filePath"),
    "File": (_build_text_for_file, "n.path, n.language"),
    "Plan": (_build_text_for_plan, "n.number, n.title, n.status, n.planType, n.filePath"),
    "Learning": (_build_text_for_learning, "n.learningId, n.description, n.target, n.status"),
    "ReviewFinding": (
        _build_text_for_review_finding,
        "n.severity, n.category, n.finding, n.resolution, n.status",
    ),
    "Study": (_build_text_for_study, "n.studyId, n.title, n.status, n.outcome, n.tags"),
    "ADR": (_build_text_for_adr, "n.number, n.title, n.status, n.filePath"),
    "Spike": (_build_text_for_spike, "n.id, n.title, n.parentPlan, n.status, n.filePath"),
    "BacklogItem": (_build_text_for_backlog, "n.id, n.title, n.priority, n.status"),
}

GOVERNANCE_TABLES = ["Plan", "Learning", "ReviewFinding", "Study", "ADR", "Spike", "BacklogItem"]
CODE_TABLES = ["Function", "Class", "Method", "File"]

# SQL SELECT queries — return dot-qualified column names so
# _build_text_for_* functions work without modification. startLine/endLine are
# selected so the embed step can read the definition's source slice and enrich
# the text with its docstring/leading comment (Plan 227).
_NODE_SELECT: dict[str, str] = {
    "Function": (
        'SELECT id AS "n.id", name AS "n.name",'
        ' signature AS "n.signature", filePath AS "n.filePath",'
        ' startLine AS "n.startLine", endLine AS "n.endLine"'
        " FROM Function"
    ),
    "Class": (
        'SELECT id AS "n.id", name AS "n.name", filePath AS "n.filePath",'
        ' startLine AS "n.startLine", endLine AS "n.endLine"'
        " FROM Class"
    ),
    "Method": (
        'SELECT id AS "n.id", name AS "n.name", className AS "n.className",'
        ' signature AS "n.signature", filePath AS "n.filePath",'
        ' startLine AS "n.startLine", endLine AS "n.endLine"'
        " FROM Method"
    ),
    "File": ('SELECT id AS "n.id", path AS "n.path", language AS "n.language" FROM File'),
    "Plan": (
        'SELECT id AS "n.id", number AS "n.number", title AS "n.title",'
        ' status AS "n.status", planType AS "n.planType", filePath AS "n.filePath"'
        " FROM Plan"
    ),
    "Learning": (
        'SELECT id AS "n.id", learningId AS "n.learningId", planNumber AS "n.planNumber",'
        ' description AS "n.description", target AS "n.target", status AS "n.status"'
        " FROM Learning"
    ),
    "ReviewFinding": (
        'SELECT id AS "n.id", reviewType AS "n.reviewType", planNumber AS "n.planNumber",'
        ' severity AS "n.severity", category AS "n.category", finding AS "n.finding",'
        ' resolution AS "n.resolution", status AS "n.status"'
        " FROM ReviewFinding"
    ),
    "Study": (
        'SELECT id AS "n.id", studyId AS "n.studyId", title AS "n.title",'
        ' studyType AS "n.studyType", status AS "n.status", outcome AS "n.outcome",'
        ' confidence AS "n.confidence", tags AS "n.tags", relatedPlans AS "n.relatedPlans",'
        ' filePath AS "n.filePath"'
        " FROM Study"
    ),
    "ADR": (
        'SELECT id AS "n.id", number AS "n.number", title AS "n.title",'
        ' status AS "n.status", date AS "n.date", filePath AS "n.filePath",'
        ' relatedPlans AS "n.relatedPlans", relatedADRs AS "n.relatedADRs"'
        " FROM ADR"
    ),
    "Spike": (
        'SELECT id AS "n.id", title AS "n.title", parentPlan AS "n.parentPlan",'
        ' status AS "n.status", created AS "n.created", filePath AS "n.filePath"'
        " FROM Spike"
    ),
    "BacklogItem": (
        'SELECT id AS "n.id", planNumber AS "n.planNumber", title AS "n.title",'
        ' priority AS "n.priority", effort AS "n.effort", status AS "n.status",'
        ' source AS "n.source"'
        " FROM BacklogItem"
    ),
}

#: Cap enrichment text so a long docstring cannot dominate the embedding input.
_MAX_DOC_CHARS = 400


def _normalize(vec: list[float]) -> list[float]:
    """L2-normalize a vector to unit length (store-time, Plan 227).

    Unit vectors make cosine similarity equal to the dot product and let an L2
    ANN index (HNSW via ``vss``) rank-order identically to cosine. A zero vector
    is returned unchanged (no division by zero).
    """
    norm = sum(x * x for x in vec) ** 0.5
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def _extract_leading_doc(source: str) -> str:
    """Pull a definition's docstring or leading comment from its source slice.

    Best-effort and language-agnostic: returns the first triple-quoted docstring
    if present, else the run of leading ``#`` / ``//`` comment lines. Collapsed to
    a single line and truncated to ``_MAX_DOC_CHARS`` so enrichment stays a hint,
    not the dominant signal. Returns ``""`` when nothing is found.
    """
    if not source:
        return ""
    text = source.lstrip()
    for quote in ('"""', "'''"):
        if quote in text:
            start = text.index(quote) + 3
            end = text.find(quote, start)
            if end != -1:
                doc = text[start:end].strip()
                if doc:
                    return " ".join(doc.split())[:_MAX_DOC_CHARS]
    comments: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            comments.append(stripped.lstrip("#").strip())
        elif stripped.startswith("//"):
            comments.append(stripped.lstrip("/").strip())
        elif comments:
            break
        elif stripped == "":
            continue
        else:
            break
    return " ".join(" ".join(comments).split())[:_MAX_DOC_CHARS]


def _enrich_text(root: Any, table: str, row: dict[str, Any]) -> str:
    """Return a docstring/comment hint for a node by reading its source slice.

    Reads ``[startLine:endLine]`` of the node's file (the whole-file head for
    ``File``) and extracts the leading doc. Returns ``""`` on any I/O problem or
    when the file is absent, so enrichment never breaks indexing.
    """
    if root is None:
        return ""
    from pathlib import Path

    rel = row.get("n.filePath") or row.get("n.path") or ""
    if not rel:
        return ""
    try:
        path = Path(rel)
        if not path.is_absolute():
            path = Path(root) / rel
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ""
    if table == "File":
        slice_text = "\n".join(lines[:40])
    else:
        try:
            start = int(row.get("n.startLine") or 0)
            end = int(row.get("n.endLine") or 0)
        except (TypeError, ValueError):
            return ""
        if start <= 0:
            return ""
        # Node line numbers are 1-based and inclusive; clamp defensively.
        body = lines[start - 1 : end if end >= start else start]
        # Skip the signature line so a function's own def line is not the "doc".
        slice_text = "\n".join(body[1:]) if len(body) > 1 else ""
    return _extract_leading_doc(slice_text)


# Node-property SELECT columns per searchable table (aliased f.*). The full
# search SQL is assembled by _build_search_sql so a project predicate and
# per-hit provenance can be injected for multi-project workspaces (Plan 225).
_NODE_SEARCH_COLS: dict[str, str] = {
    "Function": (
        'f.id AS "n.id", f.name AS "n.name",'
        ' f.signature AS "n.signature", f.filePath AS "n.filePath"'
    ),
    "Class": 'f.id AS "n.id", f.name AS "n.name", f.filePath AS "n.filePath"',
    "Method": (
        'f.id AS "n.id", f.name AS "n.name", f.className AS "n.className",'
        ' f.signature AS "n.signature", f.filePath AS "n.filePath"'
    ),
    "File": 'f.id AS "n.id", f.path AS "n.path", f.language AS "n.language"',
    "Plan": (
        'f.id AS "n.id", f.title AS "n.name", f.filePath AS "n.filePath",'
        ' f.status AS "n.status", f.number AS "n.number"'
    ),
    "Learning": (
        'f.id AS "n.id", f.learningId AS "n.name", f.target AS "n.filePath",'
        ' f.status AS "n.status", f.description AS "n.description"'
    ),
    "ReviewFinding": (
        'f.id AS "n.id", f.category AS "n.name", f.finding AS "n.description",'
        ' f.severity AS "n.severity", f.status AS "n.status", f.planNumber AS "n.number"'
    ),
    "Study": (
        'f.id AS "n.id", f.title AS "n.name", f.filePath AS "n.filePath",'
        ' f.status AS "n.status", f.outcome AS "n.description"'
    ),
    "ADR": (
        'f.id AS "n.id", f.title AS "n.name", f.filePath AS "n.filePath",'
        ' f.status AS "n.status", f.number AS "n.number"'
    ),
    "Spike": (
        'f.id AS "n.id", f.title AS "n.name", f.filePath AS "n.filePath",'
        ' f.status AS "n.status", f.parentPlan AS "n.description"'
    ),
    "BacklogItem": (
        'f.id AS "n.id", f.title AS "n.name", f.source AS "n.filePath",'
        ' f.status AS "n.status", f.priority AS "n.description"'
    ),
}


def _build_search_sql(
    table: str, scope: Any, model_name: str = DEFAULT_MODEL
) -> tuple[str, list[Any]]:
    """Assemble similarity-search SQL for *table* under *scope* (Plan 225).

    JOINs EmbeddingStore to the node table and computes list_cosine_similarity
    in-database. In multi-project mode the owning project is selected for
    provenance and, when the scope is targeted, an ``e.project = ?`` predicate
    filters to that project; federated/single-project scopes add no predicate.
    Returns ``(sql, predicate_params)`` where predicate_params is ``[]`` or
    ``[project]``; the caller prepends the query vector and appends top_k.
    """
    from agentscaffold.graph.scoping import sql_predicate

    cols = _NODE_SEARCH_COLS[table]
    provenance = ', e.project AS "n.project"' if getattr(scope, "multi", False) else ""
    frag, params = sql_predicate(scope, column="e.project")
    where_parts = ["e.model = ?"]
    if frag:
        where_parts.append(frag)
    where_extra = " AND " + " AND ".join(where_parts)
    sql = (
        f"SELECT {cols}{provenance},"
        " list_cosine_similarity(e.embedding, ?) AS similarity"
        f" FROM EmbeddingStore e JOIN {table} f ON f.id = e.node_id"
        f" WHERE e.node_type = '{table}'{where_extra}"
        " ORDER BY similarity DESC LIMIT ?"
    )
    return sql, [model_name, *params]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_enriched_text(root: Any, table: str, row: dict[str, Any]) -> str:
    """Compose the shallow NL text with a source-derived docstring hint (Plan 227)."""
    builder_fn, _fields = _TEXT_BUILDERS[table]
    base = builder_fn(row)
    doc = _enrich_text(root, table, row)
    return f"{base} | doc: {doc}" if doc else base


def generate_embeddings(
    store: GraphBackend,
    *,
    model_name: str | None = None,
    cache_dir: str | None = None,
    tables: list[str] | None = None,
    batch_size: int = 64,
    root: Any = None,
    file_paths: set[str] | None = None,
) -> dict[str, int]:
    """Generate embeddings for code definitions in the graph.

    Plan 227: embedded text is enriched with each definition's docstring/leading
    comment (read from the source slice under *root*; defaults to the resolved
    project root) and vectors are L2-normalized at store time. Both are additive
    -- with no source available the text falls back to today's name+signature.

    Returns dict of {table_name: count_embedded}.
    """
    if not _st_available:
        raise ImportError(
            "Embeddings require sentence-transformers: pip install agentscaffold[search]"
        )

    if root is None:
        try:
            from agentscaffold.paths import resolve_root

            root = resolve_root()
        except Exception:
            root = None

    active_model = _active_model_name(model_name)
    model = None
    target_tables = tables or list(_TEXT_BUILDERS.keys())
    scope = set(file_paths) if file_paths is not None else None
    result: dict[str, int] = {}

    for table in target_tables:
        if table not in _TEXT_BUILDERS:
            logger.warning("No text builder for table %s, skipping", table)
            continue

        _ensure_embedding_column(store, table)

        rows = store.query(_NODE_SELECT[table])
        if scope is not None:
            rows = [row for row in rows if _row_file_path(row) in scope]
        if not rows:
            result[table] = 0
            continue

        texts = [_build_enriched_text(root, table, r) for r in rows]
        ids = [r["n.id"] for r in rows]
        text_hashes = [_hash_text(t) for t in texts]

        count = 0
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            batch_ids = ids[i : i + batch_size]
            batch_hashes = text_hashes[i : i + batch_size]

            pending_texts: list[str] = []
            pending_ids: list[str] = []
            pending_hashes: list[str] = []
            for text, node_id, text_hash in zip(batch_texts, batch_ids, batch_hashes):
                existing = store.query_scalar(
                    "SELECT COUNT(*) FROM EmbeddingStore"
                    " WHERE node_id = ?"
                    " AND node_type = ?"
                    " AND model = ?"
                    " AND text_hash = ?",
                    {
                        "node_id": node_id,
                        "node_type": table,
                        "model": active_model,
                        "text_hash": text_hash,
                    },
                )
                if existing:
                    continue
                pending_texts.append(text)
                pending_ids.append(node_id)
                pending_hashes.append(text_hash)

            if not pending_texts:
                continue

            if model is None:
                model = _get_model(active_model, cache_dir)
            vectors = model.encode(pending_texts, show_progress_bar=False)

            for node_id, text_hash, vec in zip(pending_ids, pending_hashes, vectors):
                vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
                store.store_embedding(
                    node_id,
                    table,
                    _normalize(vec_list),
                    model=active_model,
                    text_hash=text_hash,
                )
                count += 1

        result[table] = count
        logger.info("Embedded %d %s nodes", count, table)

    ensure_hnsw = getattr(store, "ensure_embedding_hnsw_index", None)
    if callable(ensure_hnsw):
        ensure_hnsw()

    return result


def _row_file_path(row: dict[str, Any]) -> str:
    """Return the source/governance file path carried by an embedding row."""
    return str(
        row.get("n.filePath")
        or row.get("n.path")
        or row.get("n.target")
        or row.get("n.source")
        or ""
    )


def search_similar(
    store: GraphBackend,
    query: str,
    *,
    model_name: str | None = None,
    cache_dir: str | None = None,
    table: str = "Function",
    top_k: int = 10,
    project: str | None = None,
    all_projects: bool = False,
    start: Any = None,
) -> list[dict[str, Any]]:
    """Find nodes most similar to a natural-language query.

    Scope (Plan 225): in a multi-project workspace the search defaults to the
    current project. Pass ``project=`` to target another project, or
    ``all_projects=True`` to search federated across the workspace (each hit is
    then labelled with its owning project under ``n.project``). Single-project
    repos ignore scope entirely. Returns dicts with node properties and a
    rounded similarity score.
    """
    if not _st_available:
        raise ImportError(
            "Semantic search requires sentence-transformers: pip install agentscaffold[search]"
        )

    if table not in _TEXT_BUILDERS:
        raise ValueError(f"Unsupported table for search: {table}")

    from agentscaffold.graph.scoping import resolve_scope

    scope = resolve_scope(project=project, all_projects=all_projects, start=start)

    active_model = _active_model_name(model_name)
    model = _get_model(active_model, cache_dir)
    query_vec = model.encode([query], show_progress_bar=False)[0]
    query_list = query_vec.tolist() if hasattr(query_vec, "tolist") else list(query_vec)

    sql, pred_params = _build_search_sql(table, scope, active_model)
    params: dict[str, Any] = {"query_vector": query_list}
    if pred_params:
        for idx, value in enumerate(pred_params):
            params[f"pred_{idx}"] = value
    params["top_k"] = top_k
    rows = store.query(sql, params)
    return [
        {
            **{k: v for k, v in row.items() if k != "similarity"},
            "similarity": round(float(row["similarity"]), 4),
        }
        for row in rows
        if row.get("similarity") is not None
    ]


def find_duplicates(
    store: GraphBackend,
    *,
    table: str = "Function",
    threshold: float = 0.92,
    top_n: int = 50,
    model_name: str | None = None,
    start: Any = None,
) -> list[dict[str, Any]]:
    """Surface cross-project near-duplicate definitions to drive shared-library reuse.

    Pairwise cosine over the EmbeddingStore between embeddings owned by
    *different* projects, returning pairs at or above *threshold* (e.g. "this
    function is 0.94 similar to one in project B"). Only meaningful in a
    multi-project workspace; returns ``[]`` for a single-project repo. Each
    result has ``id_a``/``project_a``/``id_b``/``project_b``/``similarity``.

    Note: similarity quality is bounded by today's shallow embedding text;
    Plan 227 (enriched text + better models) materially improves precision.
    A min-size gate to cut boilerplate false positives is a documented follow-up.
    """
    from agentscaffold.graph.scoping import resolve_scope

    scope = resolve_scope(all_projects=True, start=start)
    if not getattr(scope, "multi", False):
        return []

    active_model = _active_model_name(model_name)
    sql = (
        "SELECT a.node_id AS id_a, a.project AS project_a,"
        " b.node_id AS id_b, b.project AS project_b,"
        " list_cosine_similarity(a.embedding, b.embedding) AS similarity"
        " FROM EmbeddingStore a JOIN EmbeddingStore b"
        " ON a.node_type = ? AND b.node_type = ? AND a.project < b.project"
        " WHERE a.model = ? AND b.model = ?"
        " AND list_cosine_similarity(a.embedding, b.embedding) >= ?"
        " ORDER BY similarity DESC LIMIT ?"
    )
    rows = store.query(
        sql,
        {
            "ta": table,
            "tb": table,
            "model_a": active_model,
            "model_b": active_model,
            "threshold": threshold,
            "top_n": top_n,
        },
    )
    return [
        {
            **{k: v for k, v in row.items() if k != "similarity"},
            "similarity": round(float(row["similarity"]), 4),
        }
        for row in rows
        if row.get("similarity") is not None
    ]


def embeddings_available(store: GraphBackend, model_name: str | None = None) -> bool:
    """Check if embeddings exist for the active/requested model."""
    try:
        model = _active_model_name(model_name)
        count = store.query_scalar(
            "SELECT COUNT(*) FROM EmbeddingStore WHERE model = ?", {"model": model}
        )
        return bool(count and int(count) > 0)
    except Exception:
        return False


def embeddings_model_mismatch(store: GraphBackend, model_name: str | None = None) -> bool:
    """Return True when embeddings exist, but none match the active model."""
    try:
        total = store.query_scalar("SELECT COUNT(*) FROM EmbeddingStore")
        if not total:
            return False
        return not embeddings_available(store, model_name)
    except Exception:
        return False
