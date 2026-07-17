"""
Security & QA gate — API layer.

Per AGENTS.md: "test_api.py: all endpoints return 401 without auth, 200 with valid JWT"

Covers api/tenants.py, api/leads.py, api/rag.py, api/reports.py, and the health
probe in main.py. Uses httpx.AsyncClient + ASGITransport (avoids starlette/httpx
TestClient incompatibility).

Auth strategy:
  - No header → 401
  - Malformed (Token scheme) → 401
  - Empty Bearer → 401
  - Valid Bearer → proceeds to handler (503 from stub Supabase is expected for
    Phase 1–4 — confirms auth passed and reached the handler)

Note: chat.py is tested in test_chat_api.py. main.py health probe is covered here.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Mock heavy deps before any project import
# ---------------------------------------------------------------------------

_mock_crewai = MagicMock()
_mock_langchain_anthropic = MagicMock()
_mock_langchain = MagicMock()
_mock_langchain_tools = MagicMock()


def _tool_identity(name_or_fn):
    if callable(name_or_fn):
        return name_or_fn
    return lambda fn: fn


_mock_langchain_tools.tool = _tool_identity
_mock_langchain.tools = _mock_langchain_tools
sys.modules.setdefault("crewai", _mock_crewai)
sys.modules.setdefault("langchain", _mock_langchain)
sys.modules.setdefault("langchain.tools", _mock_langchain_tools)
sys.modules.setdefault("langchain_anthropic", _mock_langchain_anthropic)
sys.modules.setdefault("langchain_core", MagicMock())
sys.modules.setdefault("langchain_core.messages", MagicMock())

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import app  # noqa: E402  — must come after sys.modules injection

_AUTH = {"Authorization": "Bearer test-token"}

# ---------------------------------------------------------------------------
# Async request helper
# ---------------------------------------------------------------------------


def _req(method: str, path: str, headers=None, **kwargs):
    if headers is None:
        headers = _AUTH

    async def _inner():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await getattr(c, method)(path, headers=headers, **kwargs)

    return asyncio.run(_inner())


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_200_no_auth_required(self):
        response = _req("get", "/", headers={})
        assert response.status_code == 200

    def test_health_returns_ok(self):
        response = _req("get", "/", headers={})
        assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Tenants — 401 without auth
# ---------------------------------------------------------------------------


class TestTenantsAuth:
    def test_list_tenants_no_auth_returns_401(self):
        assert _req("get", "/api/v1/tenants", headers={}).status_code == 401

    def test_list_tenants_bad_scheme_returns_401(self):
        assert _req("get", "/api/v1/tenants", headers={"Authorization": "Token abc"}).status_code == 401

    def test_list_tenants_empty_bearer_returns_401(self):
        assert _req("get", "/api/v1/tenants", headers={"Authorization": "Bearer "}).status_code == 401

    def test_get_tenant_no_auth_returns_401(self):
        assert _req("get", "/api/v1/tenants/tenant_001", headers={}).status_code == 401

    def test_create_tenant_no_auth_returns_401(self):
        assert _req("post", "/api/v1/tenants", headers={}, json={}).status_code == 401

    def test_update_tenant_no_auth_returns_401(self):
        assert _req("put", "/api/v1/tenants/tenant_001", headers={}, json={}).status_code == 401


class TestTenantsWithAuth:
    def test_list_tenants_valid_token_reaches_handler(self):
        # Phase 1–4: Supabase not wired → 503. Confirms auth passed.
        assert _req("get", "/api/v1/tenants").status_code == 503

    def test_get_tenant_valid_token_reaches_handler(self):
        assert _req("get", "/api/v1/tenants/tenant_001").status_code == 503

    def test_create_tenant_valid_token_reaches_handler(self):
        # Write endpoints always return 503 (Phase 5 gate)
        payload = {
            "tenant_id": "tenant_001",
            "company_name": "Acme",
            "geo_center": "Houston, TX",
            "sender_name": "Carlos",
            "sender_email": "carlos@acme.com",
            "owner_whatsapp": "+15551234567",
            "owner_name": "Carlos",
            "rag_collection": "rag_tenant_001",
        }
        assert _req("post", "/api/v1/tenants", json=payload).status_code == 503

    def test_update_tenant_valid_token_reaches_handler(self):
        assert _req("put", "/api/v1/tenants/tenant_001", json={"active": True}).status_code == 503


# ---------------------------------------------------------------------------
# Leads — 401 without auth
# ---------------------------------------------------------------------------


class TestLeadsAuth:
    def test_list_leads_no_auth_returns_401(self):
        assert _req("get", "/api/v1/leads/tenant_001", headers={}).status_code == 401

    def test_list_leads_bad_scheme_returns_401(self):
        assert _req("get", "/api/v1/leads/tenant_001", headers={"Authorization": "Token x"}).status_code == 401

    def test_list_leads_empty_bearer_returns_401(self):
        assert _req("get", "/api/v1/leads/tenant_001", headers={"Authorization": "Bearer "}).status_code == 401

    def test_get_lead_no_auth_returns_401(self):
        assert _req("get", "/api/v1/leads/tenant_001/lead-123", headers={}).status_code == 401

    def test_patch_lead_no_auth_returns_401(self):
        assert _req("patch", "/api/v1/leads/tenant_001/lead-123", headers={}, json={}).status_code == 401


class TestLeadsWithAuth:
    def test_list_leads_valid_token_reaches_handler(self):
        assert _req("get", "/api/v1/leads/tenant_001").status_code == 503

    def test_get_lead_valid_token_reaches_handler(self):
        assert _req("get", "/api/v1/leads/tenant_001/lead-abc").status_code == 503

    def test_patch_lead_valid_token_reaches_handler(self):
        assert _req("patch", "/api/v1/leads/tenant_001/lead-abc", json={"status": "contacted"}).status_code == 503

    def test_list_leads_invalid_status_returns_422(self):
        assert _req("get", "/api/v1/leads/tenant_001", params={"status": "INVALID_STATUS"}).status_code == 422

    def test_list_leads_limit_too_large_returns_422(self):
        assert _req("get", "/api/v1/leads/tenant_001", params={"limit": 999}).status_code == 422

    def test_list_leads_valid_status_filter_reaches_handler(self):
        assert _req("get", "/api/v1/leads/tenant_001", params={"status": "new"}).status_code == 503


# ---------------------------------------------------------------------------
# RAG — 401 without auth
# ---------------------------------------------------------------------------


class TestRAGAuth:
    def test_upload_no_auth_returns_401(self):
        assert _req("post", "/api/v1/rag/tenant_001/upload", headers={}).status_code == 401

    def test_upload_bad_scheme_returns_401(self):
        assert _req(
            "post", "/api/v1/rag/tenant_001/upload",
            headers={"Authorization": "Token x"},
        ).status_code == 401

    def test_status_no_auth_returns_401(self):
        assert _req("get", "/api/v1/rag/tenant_001/status", headers={}).status_code == 401

    def test_status_empty_bearer_returns_401(self):
        assert _req("get", "/api/v1/rag/tenant_001/status", headers={"Authorization": "Bearer "}).status_code == 401


class TestRAGWithAuth:
    def test_status_valid_token_reaches_handler(self):
        # query_rag gracefully returns found=False when chromadb not installed → 200
        response = _req("get", "/api/v1/rag/tenant_001/status")
        assert response.status_code == 200

    def test_status_returns_collection_name(self):
        response = _req("get", "/api/v1/rag/tenant_001/status")
        assert response.json()["collection_name"] == "rag_tenant_001"

    def test_status_tenant_isolation(self):
        r1 = _req("get", "/api/v1/rag/tenant_001/status")
        r2 = _req("get", "/api/v1/rag/tenant_002/status")
        assert r1.json()["collection_name"] == "rag_tenant_001"
        assert r2.json()["collection_name"] == "rag_tenant_002"

    def test_upload_unsupported_file_type_returns_422(self):
        import io
        response = _req(
            "post",
            "/api/v1/rag/tenant_001/upload",
            files={"file": ("bad.exe", io.BytesIO(b"data"), "application/octet-stream")},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Reports — 401 without auth
# ---------------------------------------------------------------------------


class TestReportsAuth:
    def test_daily_no_auth_returns_401(self):
        assert _req("get", "/api/v1/reports/tenant_001/daily", headers={}).status_code == 401

    def test_daily_bad_scheme_returns_401(self):
        assert _req(
            "get", "/api/v1/reports/tenant_001/daily",
            headers={"Authorization": "Token x"},
        ).status_code == 401

    def test_history_no_auth_returns_401(self):
        assert _req("get", "/api/v1/reports/tenant_001/history", headers={}).status_code == 401

    def test_history_empty_bearer_returns_401(self):
        assert _req(
            "get", "/api/v1/reports/tenant_001/history",
            headers={"Authorization": "Bearer "},
        ).status_code == 401


class TestReportsWithAuth:
    def test_daily_valid_token_reaches_handler(self):
        assert _req("get", "/api/v1/reports/tenant_001/daily").status_code == 503

    def test_daily_with_date_param_reaches_handler(self):
        assert _req(
            "get", "/api/v1/reports/tenant_001/daily",
            params={"report_date": "2026-07-01"},
        ).status_code == 503

    def test_history_valid_token_reaches_handler(self):
        assert _req("get", "/api/v1/reports/tenant_001/history").status_code == 503

    def test_history_limit_too_large_returns_422(self):
        assert _req(
            "get", "/api/v1/reports/tenant_001/history",
            params={"limit": 999},
        ).status_code == 422
