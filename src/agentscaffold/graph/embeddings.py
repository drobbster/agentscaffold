"""Code embeddings for semantic similarity search.

Generates vector embeddings for code definitions (functions, classes, methods)
using sentence-transformers. Embeddings are stored as JSON arrays in the graph
and support cosine similarity search.

Requires: pip install agentscaffold[search]
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import numpy as np

from agentscaffold.graph.backend import GraphBackend
from agentscaffold.graph.query_compat import is_duckpgq

if TYPE_CHECKING:
    pass

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
_model_cache: dict[str, Any] = {}


def _get_model(model_name: str = DEFAULT_MODEL) -> Any:
    """Load and cache a SentenceTransformer model, suppressing noisy output."""
    if model_name in _model_cache:
        return _model_cache[model_name]

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _prev_level = logging.root.level
        logging.disable(logging.WARNING)
        try:
            model = SentenceTransformer(model_name)
        finally:
            logging.disable(logging.NOTSET)
            logging.root.setLevel(_prev_level)

    _model_cache[model_name] = model
    return model


def _ensure_embedding_column(store: GraphBackend, table: str) -> None:
    """Add an embedding column to a node table if it doesn't exist.

    For DuckPGQ backends, embeddings live in the EmbeddingStore auxiliary
    table (added in schema v4), so no ALTER TABLE is required.
    """
    if is_duckpgq(store):
        return  # EmbeddingStore handles storage; no ALTER TABLE needed
    try:
        store.execute(f"ALTER TABLE {table} ADD embedding STRING DEFAULT ''")
    except Exception:
        pass


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


_TEXT_BUILDERS = {
    "Function": (_build_text_for_function, "n.name, n.signature, n.filePath"),
    "Class": (_build_text_for_class, "n.name, n.filePath"),
    "Method": (_build_text_for_method, "n.name, n.className, n.signature, n.filePath"),
    "File": (_build_text_for_file, "n.path, n.language"),
}

# DuckPGQ SQL equivalents — return the same dot-qualified column names so
# _build_text_for_* functions work without modification.
_DUCKPGQ_SELECT: dict[str, str] = {
    "Function": (
        'SELECT id AS "n.id", name AS "n.name",'
        ' signature AS "n.signature", filePath AS "n.filePath"'
        " FROM Function"
    ),
    "Class": ('SELECT id AS "n.id", name AS "n.name", filePath AS "n.filePath"' " FROM Class"),
    "Method": (
        'SELECT id AS "n.id", name AS "n.name", className AS "n.className",'
        ' signature AS "n.signature", filePath AS "n.filePath"'
        " FROM Method"
    ),
    "File": ('SELECT id AS "n.id", path AS "n.path", language AS "n.language"' " FROM File"),
}

# DuckPGQ similarity search SQL — JOIN EmbeddingStore with the node table and
# compute list_cosine_similarity in-database.  Returns same keys as the Kuzu
# path (n.id, n.<props>, similarity).
_DUCKPGQ_SEARCH_SQL: dict[str, str] = {
    "Function": (
        'SELECT f.id AS "n.id", f.name AS "n.name",'
        ' f.signature AS "n.signature", f.filePath AS "n.filePath",'
        " list_cosine_similarity(e.embedding, ?) AS similarity"
        " FROM EmbeddingStore e"
        " JOIN Function f ON f.id = e.node_id"
        " WHERE e.node_type = 'Function'"
        " ORDER BY similarity DESC LIMIT ?"
    ),
    "Class": (
        'SELECT f.id AS "n.id", f.name AS "n.name",'
        ' f.filePath AS "n.filePath",'
        " list_cosine_similarity(e.embedding, ?) AS similarity"
        " FROM EmbeddingStore e"
        " JOIN Class f ON f.id = e.node_id"
        " WHERE e.node_type = 'Class'"
        " ORDER BY similarity DESC LIMIT ?"
    ),
    "Method": (
        'SELECT f.id AS "n.id", f.name AS "n.name",'
        ' f.className AS "n.className",'
        ' f.signature AS "n.signature", f.filePath AS "n.filePath",'
        " list_cosine_similarity(e.embedding, ?) AS similarity"
        " FROM EmbeddingStore e"
        " JOIN Method f ON f.id = e.node_id"
        " WHERE e.node_type = 'Method'"
        " ORDER BY similarity DESC LIMIT ?"
    ),
    "File": (
        'SELECT f.id AS "n.id", f.path AS "n.path",'
        ' f.language AS "n.language",'
        " list_cosine_similarity(e.embedding, ?) AS similarity"
        " FROM EmbeddingStore e"
        " JOIN File f ON f.id = e.node_id"
        " WHERE e.node_type = 'File'"
        " ORDER BY similarity DESC LIMIT ?"
    ),
}


def generate_embeddings(
    store: GraphBackend,
    *,
    model_name: str = DEFAULT_MODEL,
    tables: list[str] | None = None,
    batch_size: int = 64,
) -> dict[str, int]:
    """Generate embeddings for code definitions in the graph.

    Returns dict of {table_name: count_embedded}.
    """
    if not _st_available:
        raise ImportError(
            "Embeddings require sentence-transformers: pip install agentscaffold[search]"
        )

    model = _get_model(model_name)
    target_tables = tables or list(_TEXT_BUILDERS.keys())
    result: dict[str, int] = {}

    for table in target_tables:
        if table not in _TEXT_BUILDERS:
            logger.warning("No text builder for table %s, skipping", table)
            continue

        builder_fn, fields = _TEXT_BUILDERS[table]
        _ensure_embedding_column(store, table)

        if is_duckpgq(store):
            rows = store.query(_DUCKPGQ_SELECT[table])
        else:
            rows = store.query(f"MATCH (n:{table}) RETURN n.id, {fields}")
        if not rows:
            result[table] = 0
            continue

        texts = [builder_fn(r) for r in rows]
        ids = [r["n.id"] for r in rows]

        count = 0
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            batch_ids = ids[i : i + batch_size]

            vectors = model.encode(batch_texts, show_progress_bar=False)

            for node_id, vec in zip(batch_ids, vectors):
                vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
                if is_duckpgq(store):
                    store.store_embedding(node_id, table, vec_list)
                else:
                    vec_json = json.dumps(vec_list)
                    escaped = vec_json.replace("\\", "\\\\").replace("'", "\\'")
                    store.execute(
                        f"MATCH (n:{table}) WHERE n.id = '{node_id}'"
                        f" SET n.embedding = '{escaped}'"
                    )
                count += 1

        result[table] = count
        logger.info("Embedded %d %s nodes", count, table)

    return result


def search_similar(
    store: GraphBackend,
    query: str,
    *,
    model_name: str = DEFAULT_MODEL,
    table: str = "Function",
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Find nodes most similar to a natural-language query.

    Returns list of dicts with node properties and similarity score.
    """
    if not _st_available:
        raise ImportError(
            "Semantic search requires sentence-transformers: pip install agentscaffold[search]"
        )

    model = _get_model(model_name)
    query_vec = model.encode([query], show_progress_bar=False)[0]

    if table not in _TEXT_BUILDERS:
        raise ValueError(f"Unsupported table for search: {table}")

    # DuckPGQ: use native list_cosine_similarity via EmbeddingStore JOIN
    if is_duckpgq(store):
        query_list = query_vec.tolist() if hasattr(query_vec, "tolist") else list(query_vec)
        sql = _DUCKPGQ_SEARCH_SQL[table]
        rows = store.query(sql, {"query_vector": query_list, "top_k": top_k})
        return [
            {
                **{k: v for k, v in row.items() if k != "similarity"},
                "similarity": round(float(row["similarity"]), 4),
            }
            for row in rows
            if row.get("similarity") is not None
        ]

    # KuzuDB: fetch all embeddings and compute cosine similarity in Python
    query_np = np.array(query_vec, dtype=np.float32)
    _builder_fn, fields = _TEXT_BUILDERS[table]
    rows = store.query(
        f"MATCH (n:{table}) WHERE n.embedding <> '' RETURN n.id, n.embedding, {fields}"
    )

    if not rows:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        try:
            vec = np.array(json.loads(row["n.embedding"]), dtype=np.float32)
        except (json.JSONDecodeError, TypeError):
            continue

        dot = float(np.dot(query_np, vec))
        norm_q = float(np.linalg.norm(query_np))
        norm_v = float(np.linalg.norm(vec))
        if norm_q == 0 or norm_v == 0:
            continue
        similarity = dot / (norm_q * norm_v)

        result_row = {k: v for k, v in row.items() if k != "n.embedding"}
        result_row["similarity"] = round(similarity, 4)
        scored.append((similarity, result_row))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]


def embeddings_available(store: GraphBackend) -> bool:
    """Check if any embeddings exist in the graph."""
    if is_duckpgq(store):
        try:
            count = store.query_scalar("SELECT COUNT(*) FROM EmbeddingStore")
            return bool(count and int(count) > 0)
        except Exception:
            return False
    for table in _TEXT_BUILDERS:
        try:
            count = store.query_scalar(f"MATCH (n:{table}) WHERE n.embedding <> '' RETURN count(n)")
            if count and int(count) > 0:
                return True
        except Exception:
            continue
    return False
