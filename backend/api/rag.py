"""
RAG knowledge base endpoints.

Routes:
    POST /rag/{tenant_id}/upload  — upload a document to the knowledge base
    GET  /rag/{tenant_id}/status  — check collection stats

Auth:
    All routes require Authorization: Bearer <token>.

Multi-tenant isolation:
    Each upload targets collection f"rag_{tenant_id}". No cross-tenant writes.

Phase 1–4: rag_loader.load_docs() is callable locally. Endpoint wraps it.
    Dry-run mode is respected: upload parses chunks but does not write to ChromaDB.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _require_auth(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Expected: Bearer <token>",
        )
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty Bearer token")
    return token


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class RAGUploadResponse(BaseModel):
    tenant_id: str
    filename: str
    files_processed: int
    chunks_loaded: int
    dry_run: bool


class RAGStatusResponse(BaseModel):
    tenant_id: str
    collection_name: str
    available: bool
    detail: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{tenant_id}/upload", response_model=RAGUploadResponse)
async def upload_document(
    tenant_id: str,
    file: UploadFile = File(...),
    dry_run: Optional[bool] = Form(default=None),
    token: str = Depends(_require_auth),
) -> RAGUploadResponse:
    """
    Upload a .md, .txt, or .pdf document to the tenant's knowledge base.

    The file is written to a temp path, then passed to rag_loader.load_docs().
    dry_run=true parses chunks but does not write to ChromaDB.
    """
    import tempfile, os
    from tools.rag_loader import load_docs  # lazy

    allowed = {".md", ".txt", ".pdf"}
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type {suffix!r}. Allowed: {sorted(allowed)}",
        )

    is_dry_run: bool = dry_run if dry_run is not None else settings.dry_run

    content = await file.read()
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = os.path.join(tmpdir, file.filename or "upload")
        with open(dest, "wb") as fh:
            fh.write(content)

        try:
            result = load_docs(
                tenant_id=tenant_id,
                docs_path=tmpdir,
                dry_run=is_dry_run,
            )
        except Exception as exc:
            logger.error("RAG upload error | tenant=%s | error=%s", tenant_id, exc)
            raise HTTPException(status_code=500, detail=f"RAG load failed: {exc}")

    logger.info(
        "RAG upload | tenant=%s | file=%s | chunks=%d | dry_run=%s",
        tenant_id, file.filename, result.get("chunks_loaded", 0), is_dry_run,
    )

    return RAGUploadResponse(
        tenant_id=tenant_id,
        filename=file.filename or "",
        files_processed=result.get("files_processed", 0),
        chunks_loaded=result.get("chunks_loaded", result.get("dry_run_chunks", 0)),
        dry_run=is_dry_run,
    )


@router.get("/{tenant_id}/status", response_model=RAGStatusResponse)
def rag_status(
    tenant_id: str,
    token: str = Depends(_require_auth),
) -> RAGStatusResponse:
    """
    Check whether the tenant's ChromaDB collection exists and has documents.
    Returns available=False gracefully when ChromaDB is not installed.
    """
    from tools.rag_query import query_rag  # lazy

    collection = f"rag_{tenant_id}"
    try:
        resp = query_rag(tenant_id=tenant_id, query="status check", top_k=1)
        return RAGStatusResponse(
            tenant_id=tenant_id,
            collection_name=collection,
            available=resp.found,
            detail="Collection ready" if resp.found else "Collection empty or not loaded",
        )
    except Exception as exc:
        logger.warning("RAG status check | tenant=%s | error=%s", tenant_id, exc)
        return RAGStatusResponse(
            tenant_id=tenant_id,
            collection_name=collection,
            available=False,
            detail=str(exc),
        )
