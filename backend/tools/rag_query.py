"""
Query ChromaDB per-tenant RAG collection and return context ready for prompt injection.

This file owns Contract 3 (TEAM.md): RAGChunk + RAGResponse models.
Every downstream consumer (email_agent, call_agent, director) imports
RAGResponse from here — do not change the model fields without Tech Lead approval.

Usage:
    from tools.rag_query import query_rag

    response = query_rag(
        tenant_id="tenant_001",
        query="services and pricing relevant to General Contractor companies",
    )
    if response.found:
        prompt = f"Company knowledge:\\n{response.context}\\n..."

Collection namespace: ALWAYS f"rag_{tenant_id}" — never hardcoded, never shared.
chromadb is imported lazily so this module loads fast in dry-run / test contexts.
"""

import logging
import sys
from datetime import date
from pathlib import Path
from typing import List

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Paths — must match rag_loader.py so both tools point at the same DB
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]   # growth-bizon-sales-ai/
_CHROMA_PATH = str(_REPO_ROOT / "chroma_db")
_LOGS_ROOT = _REPO_ROOT / "logs"


# ---------------------------------------------------------------------------
# Contract 3 — RAGResponse  (TEAM.md, do not change without Tech Lead sign-off)
# ---------------------------------------------------------------------------

class RAGChunk(BaseModel):
    text: str
    source_file: str
    relevance_score: float   # (0, 1] — higher is more relevant


class RAGResponse(BaseModel):
    tenant_id: str
    query: str
    chunks: List[RAGChunk]
    context: str    # chunk texts joined with separators, ready to inject into prompts
    found: bool     # False when collection missing, empty, or no results returned


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _get_logger(tenant_id: str) -> logging.Logger:
    log_dir = _LOGS_ROOT / tenant_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}.log"

    logger = logging.getLogger(f"rag_query.{tenant_id}")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _not_found(tenant_id: str, query: str) -> RAGResponse:
    return RAGResponse(
        tenant_id=tenant_id,
        query=query,
        chunks=[],
        context="",
        found=False,
    )


def _distance_to_score(distance: float) -> float:
    """
    Convert a chromadb distance value to a relevance score in (0, 1].
    Works for both L2 and cosine distances (both non-negative).
    Lower distance → score closer to 1.0.
    """
    return round(1.0 / (1.0 + max(float(distance), 0.0)), 4)


def _build_context(chunks: List[RAGChunk]) -> str:
    """Join chunk texts with a clear separator for prompt injection."""
    return "\n\n---\n\n".join(chunk.text for chunk in chunks)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_rag(
    tenant_id: str,
    query: str,
    top_k: int = 5,
) -> RAGResponse:
    """
    Query the ChromaDB collection f"rag_{tenant_id}" for chunks relevant to query.

    ALWAYS uses the tenant-namespaced collection — never crosses tenant boundaries.

    Args:
        tenant_id:  Tenant identifier, e.g. "tenant_001".
        query:      Natural language query string to embed and search.
        top_k:      Maximum number of chunks to retrieve (default 5).

    Returns:
        RAGResponse with found=False when:
          - query is blank
          - collection f"rag_{tenant_id}" does not exist (rag_loader not run yet)
          - collection exists but is empty
          - chromadb raises an unexpected error

        RAGResponse with found=True and populated chunks + context otherwise.
    """
    collection_name = f"rag_{tenant_id}"
    logger = _get_logger(tenant_id)

    if not query or not query.strip():
        logger.warning("Blank query received — returning not-found")
        return _not_found(tenant_id, query)

    logger.info(
        "RAG query | tenant=%s | collection=%s | query=%r | top_k=%d",
        tenant_id, collection_name, query, top_k,
    )

    try:
        import chromadb
        from chromadb.utils import embedding_functions

        client = chromadb.PersistentClient(path=_CHROMA_PATH)
        ef = embedding_functions.DefaultEmbeddingFunction()

        # Use get_collection (not get_or_create) — missing collection → found=False
        try:
            collection = client.get_collection(
                name=collection_name,
                embedding_function=ef,
            )
        except (ValueError, Exception) as exc:
            logger.warning(
                "Collection '%s' not found (%s) — run rag_loader.py first",
                collection_name, exc,
            )
            return _not_found(tenant_id, query)

        count = collection.count()
        if count == 0:
            logger.warning("Collection '%s' exists but is empty", collection_name)
            return _not_found(tenant_id, query)

        effective_k = min(top_k, count)
        results = collection.query(
            query_texts=[query],
            n_results=effective_k,
            include=["documents", "metadatas", "distances"],
        )

        documents: List[str] = (results.get("documents") or [[]])[0]
        metadatas: List[dict] = (results.get("metadatas") or [[]])[0]
        distances: List[float] = (results.get("distances") or [[]])[0]

        if not documents:
            logger.info("Query returned no documents")
            return _not_found(tenant_id, query)

        chunks = [
            RAGChunk(
                text=doc,
                source_file=(meta.get("filename", "") if meta else ""),
                relevance_score=_distance_to_score(dist),
            )
            for doc, meta, dist in zip(documents, metadatas, distances)
        ]

        context = _build_context(chunks)

        logger.info(
            "RAG query complete | chunks=%d | top_score=%.4f | collection=%s",
            len(chunks),
            chunks[0].relevance_score if chunks else 0.0,
            collection_name,
        )

        return RAGResponse(
            tenant_id=tenant_id,
            query=query,
            chunks=chunks,
            context=context,
            found=True,
        )

    except Exception as exc:
        logger.error("RAG query error for tenant=%s: %s", tenant_id, exc)
        return _not_found(tenant_id, query)
