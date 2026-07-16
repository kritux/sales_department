"""
Tests for backend/api/chat.py.

Uses httpx.AsyncClient + ASGITransport directly (avoids starlette 0.27 /
httpx 0.28 TestClient incompatibility where httpx removed the `app=` kwarg
from Client.__init__ that older Starlette TestClient relied on).

Each test helper calls asyncio.run() to make a fresh async request —
no special pytest-asyncio config needed.

Mock strategy:
  api.chat._load_tenant is patched to return a valid TenantConfig so the
  NotImplementedError from Supabase not being wired is bypassed.

  api.chat.generate_reply is patched to return a controlled ChatReply
  without touching the LLM or RAG.

  crewai / langchain_anthropic mocks are injected for the transitive chat_agent
  import that happens when api.chat is first imported.

Coverage:
  - Auth: missing header → 401; malformed → 401; empty token → 401
  - Auth: valid Bearer token → proceeds to handler
  - Happy path: 200 and all response fields
  - tenant_id routing: correct tenant_id passed to _load_tenant
  - Request validation: empty message → 422; missing session_id → 422
  - Tenant errors: 503 and 404 surfaced correctly
  - Handoff: intent=meeting_request propagated through response
  - Error path: generate_reply raises → 500
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException

# ---------------------------------------------------------------------------
# Inject mocks before importing api.chat (which imports chat_agent)
# ---------------------------------------------------------------------------

def _tool_identity(name_or_fn):
    if callable(name_or_fn):
        return name_or_fn
    return lambda fn: fn


_mock_langchain_tools = MagicMock()
_mock_langchain_tools.tool = _tool_identity
_mock_langchain = MagicMock()
_mock_langchain.tools = _mock_langchain_tools
sys.modules.setdefault("langchain", _mock_langchain)
sys.modules.setdefault("langchain.tools", _mock_langchain_tools)

_mock_crewai = MagicMock()
sys.modules.setdefault("crewai", _mock_crewai)

_mock_langchain_anthropic = MagicMock()
sys.modules.setdefault("langchain_anthropic", _mock_langchain_anthropic)

_mock_lc_core = MagicMock()
_mock_lc_messages = MagicMock()
sys.modules.setdefault("langchain_core", _mock_lc_core)
sys.modules.setdefault("langchain_core.messages", _mock_lc_messages)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.tenants import TenantConfig, LeadCriteria      # noqa: E402
from agents.cierre.chat_agent import ChatMessage, ChatReply  # noqa: E402
from api.chat import router                                  # noqa: E402

_app = FastAPI()
_app.include_router(router)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTH_HEADER = {"Authorization": "Bearer test-token-abc"}


def _make_tenant(**kwargs) -> TenantConfig:
    defaults = dict(
        tenant_id="tenant_001",
        company_name="Growth Bizon",
        language="en",
        geo_center="Houston, TX",
        scraping_keywords=["contractor Houston"],
        lead_criteria=LeadCriteria(industries=["contractor"]),
        sender_name="Carlos",
        sender_email="carlos@growthbizon.com",
        owner_whatsapp="+15551234567",
        owner_name="Carlos",
        rag_collection="rag_tenant_001",
    )
    defaults.update(kwargs)
    return TenantConfig(**defaults)


def _make_reply(**kwargs) -> ChatReply:
    defaults = dict(
        session_id="sess-1",
        reply="Thanks for reaching out!",
        intent="neutral",
        buying_intent=False,
        handoff_triggered=False,
        rag_found=False,
    )
    defaults.update(kwargs)
    return ChatReply(**defaults)


def _req(method: str, path: str, headers=None, **kwargs):
    """Synchronous wrapper around async httpx — fresh event loop per call."""
    if headers is None:
        headers = _AUTH_HEADER

    async def _inner():
        transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as c:
            return await getattr(c, method)(path, headers=headers, **kwargs)

    return asyncio.run(_inner())


def _post(
    tenant_id: str = "tenant_001",
    session_id: str = "sess-1",
    message: str = "Hi there",
    history: list = None,
    headers=None,
):
    payload = {"session_id": session_id, "message": message}
    if history is not None:
        payload["history"] = history
    return _req("post", f"/chat/{tenant_id}", headers=headers, json=payload)


@pytest.fixture(autouse=True)
def reset_mocks():
    _mock_crewai.reset_mock(side_effect=True)
    _mock_langchain_anthropic.reset_mock(side_effect=True)
    sys.modules["crewai"] = _mock_crewai
    sys.modules["langchain_anthropic"] = _mock_langchain_anthropic
    sys.modules["langchain.tools"] = _mock_langchain_tools
    sys.modules["langchain_core"] = _mock_lc_core
    sys.modules["langchain_core.messages"] = _mock_lc_messages
    yield


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_missing_header_returns_401(self):
        response = _post(headers={})
        assert response.status_code == 401

    def test_malformed_header_token_scheme_returns_401(self):
        response = _post(headers={"Authorization": "Token abc123"})
        assert response.status_code == 401

    def test_bearer_only_no_token_returns_401(self):
        response = _post(headers={"Authorization": "Bearer "})
        assert response.status_code == 401

    def test_valid_bearer_reaches_handler(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply()):
            response = _post(headers={"Authorization": "Bearer valid-token"})
        assert response.status_code == 200

    def test_401_response_mentions_authorization(self):
        response = _post(headers={})
        assert "Authorization" in response.text or "authorization" in response.text.lower()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_returns_200(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply()):
            response = _post()
        assert response.status_code == 200

    def test_response_has_session_id(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply(session_id="sess-42")):
            response = _post()
        assert response.json()["session_id"] == "sess-42"

    def test_response_has_reply_text(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply(reply="Hello there!")):
            response = _post()
        assert response.json()["reply"] == "Hello there!"

    def test_response_has_intent_field(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply(intent="interested")):
            response = _post()
        assert response.json()["intent"] == "interested"

    def test_buying_intent_true_propagated(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply(buying_intent=True)):
            response = _post()
        assert response.json()["buying_intent"] is True

    def test_buying_intent_false_propagated(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply(buying_intent=False)):
            response = _post()
        assert response.json()["buying_intent"] is False

    def test_handoff_triggered_true_propagated(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply(handoff_triggered=True)):
            response = _post()
        assert response.json()["handoff_triggered"] is True

    def test_rag_found_true_propagated(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply(rag_found=True)):
            response = _post()
        assert response.json()["rag_found"] is True

    def test_generate_reply_called_with_message(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply()) as mock_gr:
            _post(message="What are your prices?")
        _, kwargs = mock_gr.call_args
        msg = kwargs.get("message") or mock_gr.call_args[0][0]
        assert msg == "What are your prices?"

    def test_generate_reply_called_with_session_id(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply()) as mock_gr:
            _post(session_id="my-session-xyz")
        _, kwargs = mock_gr.call_args
        sid = kwargs.get("session_id") or mock_gr.call_args[0][3]
        assert sid == "my-session-xyz"

    def test_history_forwarded_to_generate_reply(self):
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply()) as mock_gr:
            _post(history=history)
        _, kwargs = mock_gr.call_args
        hist = kwargs.get("history") or mock_gr.call_args[0][1]
        assert len(hist) == 2

    def test_correct_tenant_id_passed_to_load_tenant(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant(tenant_id="tenant_007")) as mock_lt, \
             patch("api.chat.generate_reply", return_value=_make_reply()):
            _post(tenant_id="tenant_007")
        mock_lt.assert_called_once_with("tenant_007")


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


class TestRequestValidation:
    def test_empty_message_returns_422(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply()):
            response = _post(message="")
        assert response.status_code == 422

    def test_missing_session_id_returns_422(self):
        async def _inner():
            transport = httpx.ASGITransport(app=_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.post(
                    "/chat/tenant_001",
                    headers=_AUTH_HEADER,
                    json={"message": "Hi"},
                )
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply()):
            response = asyncio.run(_inner())
        assert response.status_code == 422

    def test_empty_session_id_returns_422(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply()):
            response = _post(session_id="")
        assert response.status_code == 422

    def test_omitted_history_defaults_to_empty(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply()) as mock_gr:
            _post()
        _, kwargs = mock_gr.call_args
        hist = kwargs.get("history", "NOT_PASSED")
        assert hist == []


# ---------------------------------------------------------------------------
# Tenant errors
# ---------------------------------------------------------------------------


class TestTenantErrors:
    def test_503_when_load_tenant_raises_http_503(self):
        with patch(
            "api.chat._load_tenant",
            side_effect=HTTPException(status_code=503, detail="not configured"),
        ):
            response = _post()
        assert response.status_code == 503

    def test_404_when_load_tenant_raises_http_404(self):
        with patch(
            "api.chat._load_tenant",
            side_effect=HTTPException(status_code=404, detail="not found"),
        ):
            response = _post()
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# generate_reply error path
# ---------------------------------------------------------------------------


class TestGenerateReplyError:
    def test_generate_reply_exception_returns_500(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", side_effect=RuntimeError("boom")):
            response = _post()
        assert response.status_code == 500

    def test_500_body_contains_error_indicator(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", side_effect=Exception("fail")):
            response = _post()
        text = response.text.lower()
        assert "error" in text or "chat" in text


# ---------------------------------------------------------------------------
# Handoff signal
# ---------------------------------------------------------------------------


class TestHandoffSignal:
    def test_meeting_request_sets_all_handoff_flags(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply(
                 intent="meeting_request",
                 buying_intent=True,
                 handoff_triggered=True,
             )):
            response = _post(message="Can we book a call?")
        data = response.json()
        assert data["intent"] == "meeting_request"
        assert data["handoff_triggered"] is True
        assert data["buying_intent"] is True

    def test_neutral_reply_has_no_handoff(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply(
                 intent="neutral",
                 buying_intent=False,
                 handoff_triggered=False,
             )):
            response = _post()
        data = response.json()
        assert data["handoff_triggered"] is False
        assert data["buying_intent"] is False

    def test_interested_intent_no_handoff(self):
        with patch("api.chat._load_tenant", return_value=_make_tenant()), \
             patch("api.chat.generate_reply", return_value=_make_reply(
                 intent="interested",
                 buying_intent=True,
                 handoff_triggered=False,
             )):
            response = _post()
        data = response.json()
        assert data["intent"] == "interested"
        assert data["handoff_triggered"] is False
