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

from agentscaffold.graph.store import GraphStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer

    _st_available = True
except ImportError:
    _st_available = False

DEFAULT_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


def _ensure_embedding_column(store: GraphStore, table: str) -> None:
    """Add an embedding column to a node table if it doesn't exist."""
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


def generate_embeddings(
    store: GraphStore,
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

    model = SentenceTransformer(model_name)
    target_tables = tables or list(_TEXT_BUILDERS.keys())
    result: dict[str, int] = {}

    for table in target_tables:
        if table not in _TEXT_BUILDERS:
            logger.warning("No text builder for table %s, skipping", table)
            continue

        builder_fn, fields = _TEXT_BUILDERS[table]
        _ensure_embedding_column(store, table)

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
                vec_json = json.dumps(vec_list)
                escaped = vec_json.replace("\\", "\\\\").replace("'", "\\'")
                store.execute(
                    f"MATCH (n:{table}) WHERE n.id = '{node_id}' " f"SET n.embedding = '{escaped}'"
                )
                count += 1

        result[table] = count
        logger.info("Embedded %d %s nodes", count, table)

    return result


def search_similar(
    store: GraphStore,
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
            "Semantic search requires sentence-transformers: " "pip install agentscaffold[search]"
        )

    model = SentenceTransformer(model_name)
    query_vec = model.encode([query], show_progress_bar=False)[0]
    query_np = np.array(query_vec, dtype=np.float32)

    if table not in _TEXT_BUILDERS:
        raise ValueError(f"Unsupported table for search: {table}")

    _builder_fn, fields = _TEXT_BUILDERS[table]
    rows = store.query(
        f"MATCH (n:{table}) WHERE n.embedding <> '' " f"RETURN n.id, n.embedding, {fields}"
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


def embeddings_available(store: GraphStore) -> bool:
    """Check if any embeddings exist in the graph."""
    for table in _TEXT_BUILDERS:
        try:
            count = store.query_scalar(f"MATCH (n:{table}) WHERE n.embedding <> '' RETURN count(n)")
            if count and int(count) > 0:
                return True
        except Exception:
            continue
    return False
