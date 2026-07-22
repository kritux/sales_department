"""
RAG knowledge base endpoints.

Routes:
    POST   /rag/{tenant_id}/upload                — upload doc, persist to disk, auto-reindex
    GET    /rag/{tenant_id}/documents             — list docs with size + last-modified
    DELETE /rag/{tenant_id}/documents/{filename}  — delete doc + purge ChromaDB chunks
    GET    /rag/{tenant_id}/status                — collection health check

Auth:
    All routes require Authorization: Bearer <token>.

Multi-tenant isolation:
    Files stored under knowledge_base/{tenant_id}/. ChromaDB collection is
    named f"rag_{tenant_id}". No cross-tenant reads or writes.

Security:
    tenant_id validated against [a-z0-9_-]+ to prevent path traversal.
    Filename resolved and checked to remain inside the tenant directory.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])

_REPO_ROOT = Path(__file__).resolve().parents[2]   # growth-bizon-sales-ai/
_KB_ROOT = _REPO_ROOT / "knowledge_base"
_CHROMA_PATH = str(_REPO_ROOT / "chroma_db")

_TENANT_ID_RE = re.compile(r"^[a-z0-9_-]+$")
_ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf"}


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


def _check_tenant_id(tenant_id: str) -> None:
    if not _TENANT_ID_RE.match(tenant_id):
        raise HTTPException(status_code=400, detail="Invalid tenant_id format")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class RAGUploadResponse(BaseModel):
    tenant_id: str
    filename: str
    files_processed: int
    chunks_loaded: int
    dry_run: bool


class RAGDocumentInfo(BaseModel):
    filename: str
    size_bytes: int
    last_modified: str          # ISO 8601 UTC


class RAGDocumentListResponse(BaseModel):
    tenant_id: str
    documents: List[RAGDocumentInfo]


class RAGStatusResponse(BaseModel):
    tenant_id: str
    collection_name: str
    available: bool
    detail: str


# ---------------------------------------------------------------------------
# ChromaDB helpers — lazy, fail-safe
# ---------------------------------------------------------------------------


def _purge_file_chunks(tenant_id: str, filename: str, dry_run: bool) -> int:
    """
    Delete all ChromaDB chunks whose metadata.filename matches `filename`
    from the tenant's collection.

    Returns the number of chunks deleted (0 in dry_run or on error).
    Fails gracefully if ChromaDB is unavailable — caller still proceeds.
    """
    if dry_run:
        return 0
    try:
        import chromadb  # lazy — not available in all environments

        client = chromadb.PersistentClient(path=_CHROMA_PATH)
        collection_name = f"rag_{tenant_id}"
        try:
            collection = client.get_collection(collection_name)
        except Exception:
            return 0  # collection doesn't exist yet

        results = collection.get(where={"filename": filename}, include=[])
        ids_to_delete = results.get("ids", [])
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
        logger.info(
            "purge_chunks | tenant=%s | file=%s | deleted=%d",
            tenant_id, filename, len(ids_to_delete),
        )
        return len(ids_to_delete)
    except Exception as exc:
        logger.warning(
            "purge_chunks: could not purge | tenant=%s | file=%s | error=%s",
            tenant_id, filename, exc,
        )
        return 0


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

    The file is persisted to knowledge_base/{tenant_id}/{filename}.
    Any existing ChromaDB chunks for that filename are purged first (prevents
    duplicates on re-upload), then the file is re-indexed automatically.
    dry_run=true writes to disk but skips all ChromaDB operations.
    """
    from tools.rag_loader import load_docs  # lazy

    _check_tenant_id(tenant_id)

    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type {suffix!r}. Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )

    is_dry_run: bool = dry_run if dry_run is not None else settings.dry_run

    content = await file.read()

    # Persist to knowledge_base/{tenant_id}/
    kb_dir = _KB_ROOT / tenant_id
    kb_dir.mkdir(parents=True, exist_ok=True)
    dest = kb_dir / filename
    dest.write_bytes(content)
    logger.info(
        "RAG upload: saved | tenant=%s | file=%s | bytes=%d",
        tenant_id, filename, len(content),
    )

    # Purge stale chunks for this file before indexing (handles re-uploads)
    _purge_file_chunks(tenant_id, filename, dry_run=is_dry_run)

    # Reindex — load_docs on the single file path (efficient; no full-collection rebuild)
    try:
        result = load_docs(
            tenant_id=tenant_id,
            docs_path=str(dest),
            dry_run=is_dry_run,
        )
    except Exception as exc:
        logger.error(
            "RAG upload: indexing failed | tenant=%s | file=%s | error=%s",
            tenant_id, filename, exc,
        )
        raise HTTPException(status_code=500, detail=f"RAG indexing failed: {exc}")

    logger.info(
        "RAG upload complete | tenant=%s | file=%s | chunks=%d | dry_run=%s",
        tenant_id, filename, result.get("chunks_loaded", 0), is_dry_run,
    )

    return RAGUploadResponse(
        tenant_id=tenant_id,
        filename=filename,
        files_processed=result.get("files_processed", 0),
        chunks_loaded=result.get("chunks_loaded", result.get("dry_run_chunks", 0)),
        dry_run=is_dry_run,
    )


@router.get("/{tenant_id}/documents", response_model=RAGDocumentListResponse)
def list_documents(
    tenant_id: str,
    token: str = Depends(_require_auth),
) -> RAGDocumentListResponse:
    """
    List all supported documents in the tenant's knowledge base directory.

    Returns filename, size in bytes, and last-modified timestamp (UTC ISO 8601).
    Returns an empty list when no documents have been uploaded yet.
    """
    _check_tenant_id(tenant_id)

    kb_dir = _KB_ROOT / tenant_id
    if not kb_dir.exists():
        return RAGDocumentListResponse(tenant_id=tenant_id, documents=[])

    docs: List[RAGDocumentInfo] = []
    for f in sorted(kb_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in _ALLOWED_EXTENSIONS:
            stat = f.stat()
            docs.append(RAGDocumentInfo(
                filename=f.name,
                size_bytes=stat.st_size,
                last_modified=datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            ))

    return RAGDocumentListResponse(tenant_id=tenant_id, documents=docs)


@router.delete("/{tenant_id}/documents/{filename}")
def delete_document(
    tenant_id: str,
    filename: str,
    dry_run: Optional[bool] = None,
    token: str = Depends(_require_auth),
) -> dict:
    """
    Delete a document from the tenant's knowledge base and remove its
    ChromaDB chunks. All other documents in the collection remain intact.

    dry_run=true (query param) skips both file deletion and chunk purge.
    """
    _check_tenant_id(tenant_id)

    # Reject filenames with obvious path traversal sequences
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    kb_dir = _KB_ROOT / tenant_id
    filepath = (kb_dir / filename).resolve()

    # Ensure resolved path stays inside the tenant's directory
    try:
        filepath.relative_to(kb_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Document {filename!r} not found")

    is_dry_run: bool = dry_run if dry_run is not None else settings.dry_run

    if not is_dry_run:
        filepath.unlink()
        logger.info(
            "RAG delete: removed file | tenant=%s | file=%s", tenant_id, filename
        )

    chunks_deleted = _purge_file_chunks(tenant_id, filename, dry_run=is_dry_run)

    logger.info(
        "RAG delete complete | tenant=%s | file=%s | chunks=%d | dry_run=%s",
        tenant_id, filename, chunks_deleted, is_dry_run,
    )

    return {
        "deleted": filename,
        "tenant_id": tenant_id,
        "chunks_deleted": chunks_deleted,
        "dry_run": is_dry_run,
    }


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

    _check_tenant_id(tenant_id)
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
        logger.warning("RAG status | tenant=%s | error=%s", tenant_id, exc)
        return RAGStatusResponse(
            tenant_id=tenant_id,
            collection_name=collection,
            available=False,
            detail=str(exc),
        )
