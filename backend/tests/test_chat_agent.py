"""
Tests for backend/agents/cierre/chat_agent.py.

Mock strategy:
  crewai, langchain, langchain_anthropic, langchain_core are all injected
  into sys.modules before import. langchain.tools.tool is replaced with an
  identity decorator so @tool("name") leaves functions as plain callables.

  _mock_llm_instance.invoke returns a MagicMock with .content set to a
  valid JSON string by default; individual tests override as needed.

  query_rag is patched per-test via unittest.mock.patch so RAG path is
  fully controlled without chromadb.

Coverage:
  - generate_reply dry_run path: stub reply, no LLM call, rag_found propagated
  - generate_reply LLM path: model selection, message building, parsing, intents
  - generate_reply error path: LLM exception returns safe error reply
  - _parse_llm_response: valid JSON, markdown fences, fallback, bad intent
  - _select_model: haiku default, sonnet on long history
  - _build_system_prompt: language variants, RAG injection, no-RAG fallback
  - build_chat_agent: Agent creation, role/goal/backstory, tool, allow_delegation
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Inject mocks BEFORE importing chat_agent
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

_mock_llm_instance = MagicMock()
_mock_llm_instance.invoke.return_value = MagicMock(
    content='{"reply": "Thanks for reaching out!", "intent": "neutral"}'
)
_mock_langchain_anthropic = MagicMock()
_mock_langchain_anthropic.ChatAnthropic.return_value = _mock_llm_instance

sys.modules.setdefault("langchain_anthropic", _mock_langchain_anthropic)

_mock_lc_core = MagicMock()
_mock_lc_messages = MagicMock()
sys.modules.setdefault("langchain_core", _mock_lc_core)
sys.modules.setdefault("langchain_core.messages", _mock_lc_messages)

# Now safe to import
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.tenants import TenantConfig, LeadCriteria  # noqa: E402
from agents.cierre.chat_agent import (  # noqa: E402
    ChatMessage,
    ChatReply,
    generate_reply,
    build_chat_agent,
    _parse_llm_response,
    _select_model,
    _build_system_prompt,
    _SONNET_TURN_THRESHOLD,
    _DRY_RUN_REPLY,
    _BUYING_INTENTS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _make_history(n: int) -> list:
    """Return n alternating user/assistant ChatMessages."""
    turns = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        turns.append(ChatMessage(role=role, content=f"Message {i}"))
    return turns


_NOT_FOUND_RAG = MagicMock(found=False, context="", chunks=[])
_FOUND_RAG = MagicMock(found=True, context="We offer web design from $800.", chunks=[MagicMock()])


@pytest.fixture(autouse=True)
def reset_mocks():
    _mock_crewai.reset_mock(side_effect=True)
    _mock_langchain_anthropic.reset_mock(side_effect=True)
    _mock_llm_instance.invoke.return_value = MagicMock(
        content='{"reply": "Thanks for reaching out!", "intent": "neutral"}'
    )
    _mock_langchain_anthropic.ChatAnthropic.return_value = _mock_llm_instance
    sys.modules["crewai"] = _mock_crewai
    sys.modules["langchain_anthropic"] = _mock_langchain_anthropic
    sys.modules["langchain.tools"] = _mock_langchain_tools
    sys.modules["langchain_core"] = _mock_lc_core
    sys.modules["langchain_core.messages"] = _mock_lc_messages
    yield


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLLMResponse:
    def test_valid_json_extracts_reply(self):
        result = _parse_llm_response('{"reply": "Hello!", "intent": "neutral"}')
        assert result["reply"] == "Hello!"

    def test_valid_json_extracts_intent(self):
        result = _parse_llm_response('{"reply": "...", "intent": "interested"}')
        assert result["intent"] == "interested"

    def test_all_valid_intents_pass_through(self):
        for intent in ("neutral", "interested", "objecting", "meeting_request"):
            r = _parse_llm_response(f'{{"reply": "x", "intent": "{intent}"}}')
            assert r["intent"] == intent

    def test_unknown_intent_defaults_to_neutral(self):
        result = _parse_llm_response('{"reply": "x", "intent": "buy_now"}')
        assert result["intent"] == "neutral"

    def test_strips_markdown_fences(self):
        raw = "```json\n{\"reply\": \"Hi\", \"intent\": \"neutral\"}\n```"
        result = _parse_llm_response(raw)
        assert result["reply"] == "Hi"

    def test_invalid_json_falls_back_to_raw_text(self):
        raw = "not valid json at all"
        result = _parse_llm_response(raw)
        assert result["reply"] == raw
        assert result["intent"] == "neutral"

    def test_empty_string_falls_back_gracefully(self):
        result = _parse_llm_response("")
        assert result["intent"] == "neutral"

    def test_json_without_reply_key_falls_back(self):
        result = _parse_llm_response('{"intent": "neutral"}')
        assert result["intent"] == "neutral"

    def test_nested_json_fallback_when_no_reply_key(self):
        result = _parse_llm_response('{"something": "else"}')
        assert "intent" in result

    def test_reply_value_coerced_to_str(self):
        result = _parse_llm_response('{"reply": 42, "intent": "neutral"}')
        assert isinstance(result["reply"], str)


# ---------------------------------------------------------------------------
# _select_model
# ---------------------------------------------------------------------------


class TestSelectModel:
    def test_haiku_for_empty_history(self):
        assert "haiku" in _select_model([], buying_intent_seen=False)

    def test_haiku_for_short_history(self):
        history = _make_history(_SONNET_TURN_THRESHOLD - 1)
        assert "haiku" in _select_model(history, buying_intent_seen=False)

    def test_sonnet_at_turn_threshold(self):
        history = _make_history(_SONNET_TURN_THRESHOLD)
        assert "sonnet" in _select_model(history, buying_intent_seen=False)

    def test_sonnet_when_buying_intent_seen(self):
        assert "sonnet" in _select_model([], buying_intent_seen=True)

    def test_sonnet_overrides_short_history_when_buying_intent(self):
        history = _make_history(1)
        assert "sonnet" in _select_model(history, buying_intent_seen=True)


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_includes_sender_name(self):
        tenant = _make_tenant(sender_name="Ana")
        prompt = _build_system_prompt(tenant, "")
        assert "Ana" in prompt

    def test_includes_company_name(self):
        tenant = _make_tenant(company_name="Soldadura Corp")
        prompt = _build_system_prompt(tenant, "")
        assert "Soldadura Corp" in prompt

    def test_english_language_rule(self):
        tenant = _make_tenant(language="en")
        prompt = _build_system_prompt(tenant, "")
        assert "English" in prompt

    def test_spanish_language_rule(self):
        tenant = _make_tenant(language="es")
        prompt = _build_system_prompt(tenant, "")
        assert "Spanish" in prompt

    def test_rag_context_injected_when_present(self):
        tenant = _make_tenant()
        ctx = "We offer web design starting at $800."
        prompt = _build_system_prompt(tenant, ctx)
        assert ctx in prompt

    def test_no_rag_uses_fallback(self):
        tenant = _make_tenant()
        prompt = _build_system_prompt(tenant, "")
        assert "professionally" in prompt or "professionally" in prompt.lower()

    def test_prompt_includes_json_format_instruction(self):
        tenant = _make_tenant()
        prompt = _build_system_prompt(tenant, "")
        assert "JSON" in prompt

    def test_prompt_includes_short_reply_rule(self):
        tenant = _make_tenant()
        prompt = _build_system_prompt(tenant, "")
        assert "SHORT" in prompt or "short" in prompt


# ---------------------------------------------------------------------------
# generate_reply — dry_run path
# ---------------------------------------------------------------------------


class TestGenerateReplyDryRun:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_returns_chat_reply(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=True)
        assert isinstance(result, ChatReply)

    def test_no_llm_call_in_dry_run(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            generate_reply("Hi", [], self.tenant, dry_run=True)
        _mock_langchain_anthropic.ChatAnthropic.assert_not_called()

    def test_stub_reply_contains_company_name(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=True)
        assert "Growth Bizon" in result.reply

    def test_stub_reply_contains_sender_name(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=True)
        assert "Carlos" in result.reply

    def test_session_id_passed_through(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, session_id="abc", dry_run=True)
        assert result.session_id == "abc"

    def test_dry_run_intent_is_neutral(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=True)
        assert result.intent == "neutral"

    def test_dry_run_handoff_false(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=True)
        assert result.handoff_triggered is False

    def test_rag_found_false_propagated(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=True)
        assert result.rag_found is False

    def test_rag_found_true_propagated(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=True)
        assert result.rag_found is True

    def test_query_rag_called_even_in_dry_run(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG) as mock_rag:
            generate_reply("Hi", [], self.tenant, dry_run=True)
        mock_rag.assert_called_once()


# ---------------------------------------------------------------------------
# generate_reply — LLM path
# ---------------------------------------------------------------------------


class TestGenerateReplyLLMPath:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_calls_llm_when_not_dry_run(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            generate_reply("Hello", [], self.tenant, dry_run=False)
        _mock_llm_instance.invoke.assert_called_once()

    def test_returns_parsed_reply_text(self):
        _mock_llm_instance.invoke.return_value = MagicMock(
            content='{"reply": "We help contractors grow online.", "intent": "neutral"}'
        )
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("What do you do?", [], self.tenant, dry_run=False)
        assert result.reply == "We help contractors grow online."

    def test_uses_haiku_for_short_conversation(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            generate_reply("Hi", [], self.tenant, dry_run=False)
        call_args = _mock_langchain_anthropic.ChatAnthropic.call_args
        model = call_args[1].get("model") or (call_args[0][0] if call_args[0] else None)
        assert "haiku" in str(model)

    def test_uses_sonnet_for_long_conversation(self):
        history = _make_history(_SONNET_TURN_THRESHOLD)
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            generate_reply("Hi", history, self.tenant, dry_run=False)
        call_args = _mock_langchain_anthropic.ChatAnthropic.call_args
        model = call_args[1].get("model") or (call_args[0][0] if call_args[0] else None)
        assert "sonnet" in str(model)

    def test_intent_neutral_sets_buying_intent_false(self):
        _mock_llm_instance.invoke.return_value = MagicMock(
            content='{"reply": "Great question.", "intent": "neutral"}'
        )
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=False)
        assert result.buying_intent is False

    def test_intent_interested_sets_buying_intent_true(self):
        _mock_llm_instance.invoke.return_value = MagicMock(
            content='{"reply": "Sounds good!", "intent": "interested"}'
        )
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("I like it", [], self.tenant, dry_run=False)
        assert result.buying_intent is True

    def test_intent_meeting_request_sets_buying_intent_true(self):
        _mock_llm_instance.invoke.return_value = MagicMock(
            content='{"reply": "Let me check the calendar.", "intent": "meeting_request"}'
        )
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Can we book a call?", [], self.tenant, dry_run=False)
        assert result.buying_intent is True

    def test_intent_meeting_request_sets_handoff_triggered(self):
        _mock_llm_instance.invoke.return_value = MagicMock(
            content='{"reply": "Let me check.", "intent": "meeting_request"}'
        )
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Let's schedule", [], self.tenant, dry_run=False)
        assert result.handoff_triggered is True

    def test_intent_interested_does_not_set_handoff(self):
        _mock_llm_instance.invoke.return_value = MagicMock(
            content='{"reply": "Tell me more.", "intent": "interested"}'
        )
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("This is interesting", [], self.tenant, dry_run=False)
        assert result.handoff_triggered is False

    def test_objecting_intent_sets_buying_intent_false(self):
        _mock_llm_instance.invoke.return_value = MagicMock(
            content='{"reply": "Understood.", "intent": "objecting"}'
        )
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Too expensive", [], self.tenant, dry_run=False)
        assert result.buying_intent is False

    def test_session_id_preserved_in_llm_path(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, session_id="sess-99", dry_run=False)
        assert result.session_id == "sess-99"

    def test_rag_context_queried_with_message(self):
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG) as mock_rag:
            generate_reply("What's your price?", [], self.tenant, dry_run=False)
        query_arg = mock_rag.call_args[1].get("query") or mock_rag.call_args[0][1]
        assert "What's your price?" in query_arg


# ---------------------------------------------------------------------------
# generate_reply — error path
# ---------------------------------------------------------------------------


class TestGenerateReplyErrorPath:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_llm_exception_returns_safe_reply(self):
        _mock_llm_instance.invoke.side_effect = RuntimeError("API down")
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=False)
        assert isinstance(result.reply, str)
        assert len(result.reply) > 0

    def test_llm_exception_does_not_raise(self):
        _mock_llm_instance.invoke.side_effect = Exception("boom")
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=False)
        assert isinstance(result, ChatReply)

    def test_llm_exception_reply_is_neutral_intent(self):
        _mock_llm_instance.invoke.side_effect = ValueError("bad")
        with patch("agents.cierre.chat_agent.query_rag", return_value=_NOT_FOUND_RAG):
            result = generate_reply("Hi", [], self.tenant, dry_run=False)
        assert result.intent == "neutral"
        assert result.buying_intent is False
        assert result.handoff_triggered is False


# ---------------------------------------------------------------------------
# build_chat_agent
# ---------------------------------------------------------------------------


class TestBuildChatAgent:
    def setup_method(self):
        self.tenant = _make_tenant()

    def test_returns_agent_instance(self):
        result = build_chat_agent(self.tenant)
        _mock_crewai.Agent.assert_called_once()
        assert result is _mock_crewai.Agent.return_value

    def test_agent_role_is_chat_specialist(self):
        build_chat_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert kwargs["role"] == "Chat Specialist"

    def test_goal_mentions_company_name(self):
        build_chat_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert "Growth Bizon" in kwargs["goal"]

    def test_backstory_mentions_sender_name(self):
        build_chat_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert "Carlos" in kwargs["backstory"]

    def test_allow_delegation_false(self):
        build_chat_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert kwargs["allow_delegation"] is False

    def test_verbose_true(self):
        build_chat_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert kwargs["verbose"] is True

    def test_agent_has_one_tool(self):
        build_chat_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert len(kwargs["tools"]) == 1

    def test_tool_is_callable(self):
        build_chat_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        assert callable(kwargs["tools"][0])

    def test_tool_calls_generate_reply(self):
        build_chat_agent(self.tenant)
        _, kwargs = _mock_crewai.Agent.call_args
        tool_fn = kwargs["tools"][0]
        with patch("agents.cierre.chat_agent.generate_reply") as mock_gr:
            mock_gr.return_value = ChatReply(
                session_id="", reply="Hi!", intent="neutral",
                buying_intent=False, handoff_triggered=False, rag_found=False,
            )
            result = tool_fn("Hello")
        mock_gr.assert_called_once()
        assert result == "Hi!"

    def test_haiku_model_used(self):
        build_chat_agent(self.tenant)
        call_args = _mock_langchain_anthropic.ChatAnthropic.call_args
        model = call_args[1].get("model") or (call_args[0][0] if call_args[0] else None)
        assert "haiku" in str(model)

    def test_different_tenants_get_different_goals(self):
        tenant_b = _make_tenant(tenant_id="tenant_002", company_name="Soldadura Corp")
        _mock_crewai.reset_mock()
        build_chat_agent(tenant_b)
        _, kwargs = _mock_crewai.Agent.call_args
        assert "Soldadura Corp" in kwargs["goal"]
        assert "Growth Bizon" not in kwargs["goal"]
