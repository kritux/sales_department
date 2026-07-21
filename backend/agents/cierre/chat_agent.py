"""
CrewAI ChatAgent for real-time inbound sales conversations.

Handles:
  - Web widget chat (frontend → POST /api/chat/{tenant_id})
  - Inbound WhatsApp messages from prospects (separate from whatsapp_tool.py,
    which sends to the *owner*; this agent replies to *prospects*)

Design:
  generate_reply() is the hot path called directly from api/chat.py.
  It queries RAG, builds a context-rich prompt, calls the LLM, and returns
  a structured ChatReply with intent classification.

  build_chat_agent() wraps generate_reply in a CrewAI Agent for batch
  workflows where the Director or a Manager delegates chat tasks.

Intent classification (every reply):
  neutral         — exploring / asking questions
  interested      — expressed positive intent, asking next steps
  objecting       — raised price / fit / trust concern
  meeting_request — explicitly asked to meet, call, or schedule

When intent == "meeting_request", handoff_triggered=True is returned so the
caller knows to invoke MeetingAgent (agents/postventa/meeting.py).

Model selection:
  Haiku  — default (fast, cheap, sufficient for Q&A)
  Sonnet — after _SONNET_TURN_THRESHOLD turns, or when buying_intent first
           appears (negotiation mode)

All crewai / langchain / langchain_anthropic imports are lazy.

Public API:
    generate_reply(message, history, tenant_config, session_id, dry_run)
        -> ChatReply
    build_chat_agent(tenant_config)
        -> crewai.Agent
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, List, Literal, Optional

from pydantic import BaseModel

from config.settings import settings
from config.tenants import TenantConfig
from tools.rag_query import query_rag

if TYPE_CHECKING:
    from crewai import Agent  # type: ignore

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOGS_ROOT = _REPO_ROOT / "logs"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SONNET_TURN_THRESHOLD = 5
_BUYING_INTENTS = frozenset({"interested", "meeting_request"})
_VALID_INTENTS = frozenset({
    "neutral", "interested", "objecting", "meeting_request",
    "out_of_scope_opportunity",
})
_DRY_RUN_REPLY = (
    "[DRY_RUN] Hi! I'm {sender_name} from {company_name}. "
    "How can I help you today?"
)

# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatReply(BaseModel):
    session_id: str
    reply: str
    intent: Literal[
        "neutral", "interested", "objecting", "meeting_request",
        "out_of_scope_opportunity",
    ] = "neutral"
    buying_intent: bool = False
    handoff_triggered: bool = False
    escalate_to_owner: bool = False
    rag_found: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_system_prompt(tenant_config: TenantConfig, rag_context: str) -> str:
    lang_rule = {
        "es": "Respond ONLY in Spanish.",
        "en": "Respond ONLY in English.",
        "both": "Match the language the prospect is using.",
    }.get(tenant_config.language, "Respond in English.")

    knowledge = (
        f"Knowledge about {tenant_config.company_name}:\n{rag_context}"
        if rag_context
        else f"You represent {tenant_config.company_name}. Answer professionally."
    )

    industries = (
        getattr(tenant_config.lead_criteria, "industries", None) or []
        if tenant_config.lead_criteria
        else []
    )
    targeting_block = ""
    if industries:
        targeting_block = (
            f"Target industries: {', '.join(industries)}.\n"
            "If the prospect is in a DIFFERENT industry: do NOT decline or close the door. "
            "Respond warmly — say this type of project is handled as a personalized case "
            "and that you need to check with the team/CEO to evaluate if you can take it on. "
            "Ask for their contact info (name + phone or email) if not yet provided. "
            "Let them know someone will follow up. Set intent to 'out_of_scope_opportunity'.\n\n"
        )

    return (
        f"You are {tenant_config.sender_name}, a sales representative at "
        f"{tenant_config.company_name}. {lang_rule}\n\n"
        f"{knowledge}\n\n"
        f"{targeting_block}"
        "STRICT RULES:\n"
        "1. Keep replies SHORT — 1 to 3 sentences maximum. This is chat, not email.\n"
        "2. Be natural and conversational — never robotic or scripted.\n"
        "3. Use the knowledge above to answer questions about services and pricing.\n"
        "4. Use the objection responses from the knowledge above when challenged.\n"
        "5. Never reveal you are AI unless directly asked 'are you a bot?'.\n"
        "6. When the prospect wants to schedule — set intent to 'meeting_request'.\n"
        "7. Answer what was asked, then ask ONE follow-up question — never info-dump.\n\n"
        "You MUST respond with a single valid JSON object:\n"
        '{"reply": "your text here", "intent": "neutral|interested|objecting|meeting_request|out_of_scope_opportunity"}\n\n'
        "intent values:\n"
        "  neutral                  — exploring or asking general questions\n"
        "  interested               — expressed positive interest in moving forward\n"
        "  objecting                — raised a concern about price, fit, or trust\n"
        "  meeting_request          — asked to schedule a call, demo, or meeting\n"
        "  out_of_scope_opportunity — prospect outside target industries; collected their info for owner review\n\n"
        "Output ONLY the JSON object. Nothing outside it."
    )


def _parse_llm_response(raw_text: str) -> dict:
    """
    Extract {reply, intent} from LLM output.
    Strips markdown fences if present; falls back to raw text on parse failure.
    """
    text = raw_text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict) and "reply" in data:
            raw_intent = data.get("intent", "neutral")
            intent = raw_intent if raw_intent in _VALID_INTENTS else "neutral"
            return {"reply": str(data["reply"]), "intent": intent}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    logger.warning("chat_agent: LLM did not return valid JSON — using raw text")
    return {"reply": text, "intent": "neutral"}


def _select_model(history: List[ChatMessage], buying_intent_seen: bool) -> str:
    if len(history) >= _SONNET_TURN_THRESHOLD or buying_intent_seen:
        return "claude-sonnet-20240229"
    return "claude-haiku-20240307"


def _build_lc_messages(
    history: List[ChatMessage],
    system_prompt: str,
    current_message: str,
) -> list:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # lazy

    msgs: list = [SystemMessage(content=system_prompt)]
    for turn in history:
        if turn.role == "user":
            msgs.append(HumanMessage(content=turn.content))
        else:
            msgs.append(AIMessage(content=turn.content))
    msgs.append(HumanMessage(content=current_message))
    return msgs


# ---------------------------------------------------------------------------
# Public API — generate_reply
# ---------------------------------------------------------------------------


def generate_reply(
    message: str,
    history: List[ChatMessage],
    tenant_config: TenantConfig,
    session_id: str = "",
    dry_run: Optional[bool] = None,
) -> ChatReply:
    """
    Generate a conversational sales reply for an inbound chat message.

    Args:
        message:       Prospect's latest message.
        history:       Prior turns oldest-first (user/assistant alternating).
        tenant_config: Company identity, language, RAG collection name.
        session_id:    Opaque session ID passed through to the reply.
        dry_run:       True → stub reply, no LLM call. None → settings.dry_run.

    Returns:
        ChatReply with reply text, intent, and handoff flag.
    """
    is_dry_run: bool = dry_run if dry_run is not None else settings.dry_run
    tenant_id = tenant_config.tenant_id

    logger.info(
        "chat_agent.generate_reply | tenant=%s | session=%s | turns=%d | dry_run=%s",
        tenant_id, session_id, len(history), is_dry_run,
    )

    # --- RAG context (attempted even in dry_run so rag_found is accurate) ---
    rag_resp = query_rag(
        tenant_id=tenant_id,
        query=f"{message} {tenant_config.company_name} services pricing",
        top_k=3,
    )
    rag_context = rag_resp.context if rag_resp.found else ""
    logger.info(
        "chat_agent: RAG | tenant=%s | found=%s | chars=%d",
        tenant_id, rag_resp.found, len(rag_context),
    )

    # --- DRY_RUN fast path --------------------------------------------------
    if is_dry_run:
        stub = _DRY_RUN_REPLY.format(
            sender_name=tenant_config.sender_name,
            company_name=tenant_config.company_name,
        )
        logger.info("[DRY_RUN] chat_agent: stub reply | tenant=%s", tenant_id)
        return ChatReply(
            session_id=session_id,
            reply=stub,
            intent="neutral",
            buying_intent=False,
            handoff_triggered=False,
            escalate_to_owner=False,
            rag_found=rag_resp.found,
        )

    # --- LLM call -----------------------------------------------------------
    from langchain_anthropic import ChatAnthropic  # lazy

    model_name = _select_model(history, buying_intent_seen=False)
    llm = ChatAnthropic(model=model_name, temperature=0.4)

    system_prompt = _build_system_prompt(tenant_config, rag_context)

    try:
        lc_messages = _build_lc_messages(history, system_prompt, message)
        ai_response = llm.invoke(lc_messages)
        raw_text = (
            ai_response.content
            if hasattr(ai_response, "content")
            else str(ai_response)
        )
    except Exception as exc:
        logger.error(
            "chat_agent: LLM call failed | tenant=%s | error=%s", tenant_id, exc
        )
        return ChatReply(
            session_id=session_id,
            reply="Sorry, I'm having trouble responding right now. Please try again.",
            intent="neutral",
            buying_intent=False,
            handoff_triggered=False,
            escalate_to_owner=False,
            rag_found=rag_resp.found,
        )

    # --- Parse and classify -------------------------------------------------
    parsed = _parse_llm_response(raw_text)
    reply_text: str = parsed["reply"]
    intent: str = parsed["intent"]

    buying_intent = intent in _BUYING_INTENTS
    handoff_triggered = intent == "meeting_request"
    escalate_to_owner = intent == "out_of_scope_opportunity"

    if handoff_triggered:
        logger.info(
            "chat_agent: HANDOFF triggered | tenant=%s | session=%s — "
            "caller should invoke MeetingAgent",
            tenant_id, session_id,
        )
    if escalate_to_owner:
        logger.info(
            "chat_agent: OUT_OF_SCOPE escalation | tenant=%s | session=%s — "
            "owner should decide whether to pursue",
            tenant_id, session_id,
        )

    logger.info(
        "chat_agent: done | tenant=%s | intent=%s | handoff=%s | escalate=%s",
        tenant_id, intent, handoff_triggered, escalate_to_owner,
    )

    return ChatReply(
        session_id=session_id,
        reply=reply_text,
        intent=intent,  # type: ignore[arg-type]
        buying_intent=buying_intent,
        handoff_triggered=handoff_triggered,
        escalate_to_owner=escalate_to_owner,
        rag_found=rag_resp.found,
    )


# ---------------------------------------------------------------------------
# Public API — build_chat_agent (CrewAI wrapper)
# ---------------------------------------------------------------------------


def build_chat_agent(tenant_config: TenantConfig) -> "Agent":
    """
    Build a CrewAI Agent that handles inbound chat tasks.

    Wraps generate_reply() as a LangChain tool so a Manager can delegate
    single-turn replies. For low-latency web chat, api/chat.py calls
    generate_reply() directly.

    Args:
        tenant_config: Fully populated TenantConfig.

    Returns:
        CrewAI Agent configured as Chat Specialist.
    """
    from crewai import Agent  # lazy
    from langchain.tools import tool  # lazy
    from langchain_anthropic import ChatAnthropic  # lazy

    tc = tenant_config  # captured in closure

    @tool("reply_to_prospect")
    def reply_to_prospect(message: str) -> str:
        """
        Generate a conversational sales reply to a prospect's chat message.
        Returns the reply text only (plain string, not JSON).
        """
        result = generate_reply(
            message=message,
            history=[],
            tenant_config=tc,
            session_id="crewai_batch",
        )
        return result.reply

    haiku = ChatAnthropic(model="claude-haiku-20240307")

    return Agent(
        role="Chat Specialist",
        goal=(
            f"Handle real-time inbound chat conversations for "
            f"{tenant_config.company_name}. Answer questions naturally, "
            f"handle objections, and identify prospects ready to book a meeting."
        ),
        backstory=(
            f"You are {tenant_config.sender_name}, a skilled sales representative "
            f"at {tenant_config.company_name}. You know the company's services, "
            f"pricing, and how to turn a curious prospect into a booked meeting."
        ),
        llm=haiku,
        tools=[reply_to_prospect],
        verbose=True,
        allow_delegation=False,
    )
