"""
Tests for backend/api/rag.py — knowledge base API endpoints.

Strategy:
  - httpx.AsyncClient + ASGITransport (avoids Starlette 0.27 / httpx 0.28 compat issue).
  - Authorization: Bearer test-token on every call satisfies _require_auth.
  - _KB_ROOT is patched per-test so no real files are touched.
  - load_docs and _purge_file_chunks are patched to avoid ChromaDB / LlamaIndex.
  - Tests that need real file deletion pass ?dry_run=false as a query param.

Coverage:
  - POST /{tenant_id}/upload: success, file persisted, unsupported ext, auth required,
    purge-before-load ordering, dry_run propagated, indexing error → 500
  - GET /{tenant_id}/documents: list, empty, required fields, csv excluded, auth
  - DELETE /{tenant_id}/documents/{filename}: deletes file, 404, purge called,
    dry_run keeps file, auth required, path traversal blocked
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api.rag as rag_module
from api.rag import router
import tools.rag_loader  # ensure in sys.modules so lazy import inside endpoint can be patched

_app = FastAPI()
_app.include_router(router)  # router already has prefix="/rag" — no extra prefix

HEADERS = {"Authorization": "Bearer test-token"}
_LOAD_OK = {"files_processed": 1, "chunks_loaded": 5, "skipped": 0}
_LOAD_DRY = {"files_processed": 1, "chunks_loaded": 0, "skipped": 0, "dry_run_chunks": 3}

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _client():
    return httpx.AsyncClient(
        transport=ASGITransport(app=_app),
        base_url="http://test",
    )


def _make_kb(tmp_path: Path, tenant_id: str) -> Path:
    kb = tmp_path / tenant_id
    kb.mkdir(parents=True)
    (kb / "servicios.md").write_text("# Servicios\nContenido.", encoding="utf-8")
    (kb / "precios.md").write_text("# Precios\nStarter $800.", encoding="utf-8")
    (kb / "ignore.csv").write_text("col1,col2", encoding="utf-8")
    return kb


# ---------------------------------------------------------------------------
# POST /{tenant_id}/upload
# ---------------------------------------------------------------------------

class TestUploadDocument:
    async def test_upload_md_returns_200(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("tools.rag_loader.load_docs", return_value=_LOAD_OK), \
                 patch("api.rag._purge_file_chunks", return_value=0):
                resp = await ac.post(
                    "/rag/tenant_001/upload",
                    headers=HEADERS,
                    files={"file": ("services.md", b"# Services", "text/markdown")},
                )
        assert resp.status_code == 200

    async def test_upload_response_fields(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("tools.rag_loader.load_docs", return_value=_LOAD_OK), \
                 patch("api.rag._purge_file_chunks", return_value=0):
                resp = await ac.post(
                    "/rag/tenant_001/upload",
                    headers=HEADERS,
                    files={"file": ("notes.txt", b"content", "text/plain")},
                )
        data = resp.json()
        assert data["tenant_id"] == "tenant_001"
        assert data["filename"] == "notes.txt"
        assert data["chunks_loaded"] == 5

    async def test_upload_persists_file_to_disk(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("tools.rag_loader.load_docs", return_value=_LOAD_OK), \
                 patch("api.rag._purge_file_chunks", return_value=0):
                await ac.post(
                    "/rag/tenant_001/upload",
                    headers=HEADERS,
                    files={"file": ("saved.md", b"# Saved", "text/markdown")},
                )
        assert (tmp_path / "tenant_001" / "saved.md").exists()

    async def test_upload_creates_kb_directory(self, tmp_path):
        assert not (tmp_path / "tenant_new").exists()
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("tools.rag_loader.load_docs", return_value=_LOAD_OK), \
                 patch("api.rag._purge_file_chunks", return_value=0):
                await ac.post(
                    "/rag/tenant_new/upload",
                    headers=HEADERS,
                    files={"file": ("doc.md", b"content", "text/markdown")},
                )
        assert (tmp_path / "tenant_new").is_dir()

    async def test_upload_rejects_csv(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.post(
                    "/rag/tenant_001/upload",
                    headers=HEADERS,
                    files={"file": ("data.csv", b"a,b", "text/csv")},
                )
        assert resp.status_code == 422

    async def test_upload_rejects_html(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.post(
                    "/rag/tenant_001/upload",
                    headers=HEADERS,
                    files={"file": ("page.html", b"<html>", "text/html")},
                )
        assert resp.status_code == 422

    async def test_upload_requires_auth(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.post(
                    "/rag/tenant_001/upload",
                    files={"file": ("x.md", b"#", "text/markdown")},
                )
        assert resp.status_code == 401

    async def test_upload_purge_called_before_load_docs(self, tmp_path):
        call_order: list = []
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks",
                       side_effect=lambda *a, **kw: call_order.append("purge") or 0), \
                 patch("tools.rag_loader.load_docs",
                       side_effect=lambda *a, **kw: call_order.append("load") or _LOAD_OK):
                await ac.post(
                    "/rag/tenant_001/upload",
                    headers=HEADERS,
                    files={"file": ("doc.md", b"# Doc", "text/markdown")},
                )
        assert call_order == ["purge", "load"]

    async def test_upload_dry_run_passed_to_load_docs(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=0), \
                 patch("tools.rag_loader.load_docs", return_value=_LOAD_DRY) as mock_load:
                await ac.post(
                    "/rag/tenant_001/upload",
                    headers=HEADERS,
                    data={"dry_run": "true"},
                    files={"file": ("doc.md", b"# Doc", "text/markdown")},
                )
        _, kwargs = mock_load.call_args
        assert kwargs.get("dry_run") is True

    async def test_upload_dry_run_reflected_in_response(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=0), \
                 patch("tools.rag_loader.load_docs", return_value=_LOAD_DRY):
                resp = await ac.post(
                    "/rag/tenant_001/upload",
                    headers=HEADERS,
                    data={"dry_run": "true"},
                    files={"file": ("doc.md", b"# Doc", "text/markdown")},
                )
        assert resp.json()["dry_run"] is True

    async def test_upload_load_failure_returns_500(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=0), \
                 patch("tools.rag_loader.load_docs", side_effect=RuntimeError("chroma down")):
                resp = await ac.post(
                    "/rag/tenant_001/upload",
                    headers=HEADERS,
                    files={"file": ("doc.md", b"# Doc", "text/markdown")},
                )
        assert resp.status_code == 500

    async def test_upload_accepts_pdf(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("tools.rag_loader.load_docs", return_value=_LOAD_OK), \
                 patch("api.rag._purge_file_chunks", return_value=0):
                resp = await ac.post(
                    "/rag/tenant_001/upload",
                    headers=HEADERS,
                    files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
                )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /{tenant_id}/documents
# ---------------------------------------------------------------------------

class TestListDocuments:
    async def test_returns_200(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.get("/rag/tenant_001/documents", headers=HEADERS)
        assert resp.status_code == 200

    async def test_lists_md_files(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.get("/rag/tenant_001/documents", headers=HEADERS)
        filenames = {d["filename"] for d in resp.json()["documents"]}
        assert "servicios.md" in filenames
        assert "precios.md" in filenames

    async def test_excludes_csv(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.get("/rag/tenant_001/documents", headers=HEADERS)
        filenames = {d["filename"] for d in resp.json()["documents"]}
        assert "ignore.csv" not in filenames

    async def test_returns_empty_list_when_no_directory(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.get("/rag/tenant_999/documents", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["documents"] == []

    async def test_document_info_fields(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.get("/rag/tenant_001/documents", headers=HEADERS)
        doc = resp.json()["documents"][0]
        assert "filename" in doc
        assert "size_bytes" in doc
        assert isinstance(doc["size_bytes"], int) and doc["size_bytes"] > 0
        assert "last_modified" in doc
        datetime.fromisoformat(doc["last_modified"])  # must be valid ISO 8601

    async def test_tenant_id_in_response(self, tmp_path):
        _make_kb(tmp_path, "tenant_002")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.get("/rag/tenant_002/documents", headers=HEADERS)
        assert resp.json()["tenant_id"] == "tenant_002"

    async def test_requires_auth(self, tmp_path):
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.get("/rag/tenant_001/documents")
        assert resp.status_code == 401

    async def test_empty_directory_returns_empty_list(self, tmp_path):
        (tmp_path / "tenant_001").mkdir()
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.get("/rag/tenant_001/documents", headers=HEADERS)
        assert resp.json()["documents"] == []


# ---------------------------------------------------------------------------
# DELETE /{tenant_id}/documents/{filename}
# ---------------------------------------------------------------------------

class TestDeleteDocument:
    async def test_delete_returns_200(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=3):
                resp = await ac.delete(
                    "/rag/tenant_001/documents/servicios.md?dry_run=false",
                    headers=HEADERS,
                )
        assert resp.status_code == 200

    async def test_delete_removes_file_from_disk(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=3):
                await ac.delete(
                    "/rag/tenant_001/documents/servicios.md?dry_run=false",
                    headers=HEADERS,
                )
        assert not (tmp_path / "tenant_001" / "servicios.md").exists()

    async def test_delete_response_payload(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=7):
                resp = await ac.delete(
                    "/rag/tenant_001/documents/servicios.md?dry_run=false",
                    headers=HEADERS,
                )
        data = resp.json()
        assert data["deleted"] == "servicios.md"
        assert data["tenant_id"] == "tenant_001"
        assert data["chunks_deleted"] == 7

    async def test_delete_calls_purge_chunks(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=4) as mock_purge:
                await ac.delete(
                    "/rag/tenant_001/documents/servicios.md?dry_run=false",
                    headers=HEADERS,
                )
        mock_purge.assert_called_once()
        assert mock_purge.call_args[0][1] == "servicios.md"

    async def test_delete_missing_returns_404(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=0):
                resp = await ac.delete(
                    "/rag/tenant_001/documents/does_not_exist.md",
                    headers=HEADERS,
                )
        assert resp.status_code == 404

    async def test_delete_requires_auth(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path):
                resp = await ac.delete("/rag/tenant_001/documents/servicios.md")
        assert resp.status_code == 401

    async def test_delete_dry_run_keeps_file(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=0):
                resp = await ac.delete(
                    "/rag/tenant_001/documents/servicios.md?dry_run=true",
                    headers=HEADERS,
                )
        assert resp.status_code == 200
        assert (tmp_path / "tenant_001" / "servicios.md").exists()

    async def test_delete_dry_run_flag_in_response(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=0):
                resp = await ac.delete(
                    "/rag/tenant_001/documents/servicios.md?dry_run=true",
                    headers=HEADERS,
                )
        assert resp.json()["dry_run"] is True

    async def test_delete_rejects_dotfile(self, tmp_path):
        _make_kb(tmp_path, "tenant_001")
        async with await _client() as ac:
            with patch.object(rag_module, "_KB_ROOT", tmp_path), \
                 patch("api.rag._purge_file_chunks", return_value=0):
                resp = await ac.delete(
                    "/rag/tenant_001/documents/.hidden",
                    headers=HEADERS,
                )
        assert resp.status_code in (400, 404)
