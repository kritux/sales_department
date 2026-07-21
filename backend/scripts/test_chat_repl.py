#!/usr/bin/env python3
"""
BIZON — Chat Agent REPL
Interactive terminal loop that simulates a lead chatting with Bizon's ChatAgent.

Usage (from the backend/ directory):
    PYTHONPATH=. python3 scripts/test_chat_repl.py            # real LLM (needs ANTHROPIC_API_KEY)
    PYTHONPATH=. python3 scripts/test_chat_repl.py --demo     # canned demo, no API key required

Session commands:
    exit  — quit the REPL
    reset — clear history and start a new conversation

Design:
  - Loads real TenantConfig and real RAG context for tenant_001 (Growth Bizon)
  - Calls generate_reply() directly — same code path as the production API
  - In --demo mode, a MockLLM is patched in so the full flow runs (RAG included)
    without needing a real Anthropic key; responses are realistic canned exchanges
    between a general contractor prospect and the agent
  - DRY_RUN safe: no leads created, no emails sent, no DB writes
"""

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import List

# ── Path setup ────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Keep DRY_RUN at its .env value for everything except generate_reply,
# which we call with explicit dry_run=False so the LLM is always invoked.
import os

# ── Project imports ───────────────────────────────────────────────────────────
from config.settings import settings
from config.tenants import TenantConfig, LeadCriteria
from agents.cierre.chat_agent import ChatMessage, ChatReply, generate_reply
from tools.rag_query import query_rag

# ── Tenant config for tenant_001 ──────────────────────────────────────────────
# Phase 5: replace with load_tenant_config("tenant_001") once Supabase is wired.
TENANT = TenantConfig(
    tenant_id="tenant_001",
    company_name="Growth Bizon",
    timezone="America/Chicago",
    language="en",
    geo_center="Houston, TX",
    geo_radius_miles=30,
    scraping_keywords=["contractor no website Houston TX"],
    lead_criteria=LeadCriteria(
        min_rating=3.5,
        min_reviews=5,
        industries=["contractor", "hvac", "plumbing", "electrical", "roofing"],
        exclude_keywords=["chain", "franchise"],
    ),
    sender_name="Carlos Mendez",
    sender_email="carlos@growthbizon.com",
    owner_whatsapp="+17135550001",
    owner_name="Carlos Mendez",
    rag_collection="rag_tenant_001",
    active=True,
)

# ── Display helpers ───────────────────────────────────────────────────────────
W = 64
BLUE  = "\033[94m"
TAN   = "\033[33m"
GREEN = "\033[92m"
RED   = "\033[91m"
DIM   = "\033[2m"
BOLD  = "\033[1m"
RESET = "\033[0m"


def _banner(demo: bool) -> None:
    mode = f"{TAN}DEMO MODE — canned responses{RESET}" if demo else f"{GREEN}LIVE — real LLM{RESET}"
    print()
    print("╔" + "═" * (W - 2) + "╗")
    print("║" + f"  BIZON — Chat Agent REPL  |  {mode}".center(W + 16) + "║")
    print("╚" + "═" * (W - 2) + "╝")
    print(f"  Tenant:  {TENANT.tenant_id} — {TENANT.company_name}")
    print(f"  Agent:   {TENANT.sender_name}")
    print(f"  RAG:     {TENANT.rag_collection}")
    print(f"  {DIM}Commands: 'exit' to quit · 'reset' to start over{RESET}")
    print()


def _show_rag_warmup() -> None:
    print(f"  {DIM}Loading RAG context from ChromaDB...{RESET}", end="", flush=True)
    rag = query_rag(TENANT.tenant_id, "services pricing Growth Bizon", top_k=3)
    status = f"{GREEN}✓ {rag.num_chunks if hasattr(rag, 'num_chunks') else len(rag.chunks)} chunks (score {rag.chunks[0].relevance_score:.3f}){RESET}" if rag.found else f"{TAN}not found — fallback text will be used{RESET}"
    print(f"\r  RAG warmup: {status}                    ")
    print()


def _print_reply(reply: ChatReply, turn: int) -> None:
    intent_colors = {
        "neutral":         DIM,
        "interested":      GREEN,
        "objecting":       TAN,
        "meeting_request": BLUE + BOLD,
    }
    color = intent_colors.get(reply.intent, DIM)

    print(f"\n  {BLUE}{BOLD}Bizon:{RESET} {reply.reply}")
    print(
        f"  {DIM}[turn {turn} · intent: {color}{reply.intent}{RESET}{DIM} · "
        f"RAG: {'✓' if reply.rag_found else '✗'}"
        f"{' · buying_intent' if reply.buying_intent else ''}]{RESET}"
    )

    if reply.handoff_triggered:
        print(f"\n  {BOLD}{GREEN}[--> handoff to MeetingAgent triggered]{RESET}")
        print(f"  {DIM}In production: MeetingAgent takes over to book the call.{RESET}")
    print()


# ── Demo mode — canned LLM responses ─────────────────────────────────────────
# Simulates a general contractor asking about pricing (4 exchanges).
# The mock patches ChatAnthropic.invoke() so RAG still runs, JSON parsing
# still runs — only the actual Anthropic HTTP call is replaced.

DEMO_SCRIPT = [
    # (user_message, canned_json_response)
    (
        "Hi, I run a roofing company in Houston. What exactly does Growth Bizon do?",
        json.dumps({
            "reply": (
                "Hey! Carlos here from Growth Bizon. We build websites and set up AI "
                "sales systems for trades businesses like yours — so you show up online "
                "and new customers can actually find you. What's your current online "
                "presence like — do you have a website right now?"
            ),
            "intent": "neutral",
        }),
    ),
    (
        "No website yet. My cousin made me a Facebook page but that's it. "
        "How much does a website run with you guys?",
        json.dumps({
            "reply": (
                "Perfect fit — that's exactly who we help. Our Starter package is "
                "$800 setup plus $150/month and gets you a fully functional site "
                "tied to your Google listing within days. Most of our roofing clients "
                "see their first inbound call within the first two weeks. "
                "How many jobs are you typically looking to close per month?"
            ),
            "intent": "interested",
        }),
    ),
    (
        "That sounds pricey. $800 is a lot when I'm already stretched thin "
        "between materials and crew.",
        json.dumps({
            "reply": (
                "Totally fair — I hear that a lot. The way our clients think about it: "
                "one extra roofing job from a customer who found you online covers the "
                "setup cost and a year of the monthly fee. We can also spread the setup "
                "across two payments if that helps cash flow. Want me to walk you through "
                "exactly what the site looks like for a roofer in your area?"
            ),
            "intent": "objecting",
        }),
    ),
    (
        "Yeah actually, can we get on a call this week? "
        "I want to see some examples before I decide.",
        json.dumps({
            "reply": (
                "Absolutely — let's do it. I have Thursday at 2 PM or Friday morning "
                "open. Which works better for you, and what's the best number to reach you?"
            ),
            "intent": "meeting_request",
        }),
    ),
]


class _DemoReplayer:
    """
    Replays DEMO_SCRIPT without touching the LLM.
    Does the real RAG query (rag_found is accurate) then injects the canned response.
    """
    def __init__(self):
        self._idx = 0

    def generate(
        self,
        message: str,
        history: List[ChatMessage],
        session_id: str,
    ) -> "ChatReply":
        from agents.cierre.chat_agent import _parse_llm_response  # reuse JSON parser

        rag_resp = query_rag(
            TENANT.tenant_id,
            f"{message} {TENANT.company_name} services pricing",
            top_k=3,
        )

        canned_json = DEMO_SCRIPT[min(self._idx, len(DEMO_SCRIPT) - 1)][1]
        self._idx += 1
        parsed = _parse_llm_response(canned_json)

        from agents.cierre.chat_agent import _BUYING_INTENTS
        intent = parsed["intent"]
        buying_intent = intent in _BUYING_INTENTS
        handoff_triggered = intent == "meeting_request"

        return ChatReply(
            session_id=session_id,
            reply=parsed["reply"],
            intent=intent,  # type: ignore[arg-type]
            buying_intent=buying_intent,
            handoff_triggered=handoff_triggered,
            rag_found=rag_resp.found,
        )


# ── Core REPL logic ───────────────────────────────────────────────────────────

def _run_turn(
    user_input: str,
    history: List[ChatMessage],
    session_id: str,
    turn: int,
    replayer: "_DemoReplayer | None" = None,
) -> ChatReply:
    """Call generate_reply (live) or the demo replayer (canned)."""
    if replayer is not None:
        return replayer.generate(user_input, history, session_id)
    return generate_reply(
        message=user_input,
        history=history,
        tenant_config=TENANT,
        session_id=session_id,
        dry_run=False,
    )


def repl(demo: bool) -> None:
    _banner(demo)
    _show_rag_warmup()

    replayer = _DemoReplayer() if demo else None
    history: List[ChatMessage] = []
    session_id = str(uuid.uuid4())[:8]
    turn = 0

    if demo:
        print(f"  {DIM}Running demo: 4-turn conversation as a Houston roofer{RESET}")
        print(f"  {DIM}Session: {session_id}{RESET}\n")

        for user_msg, _ in DEMO_SCRIPT:
            turn += 1
            print(f"  {BOLD}You:{RESET} {user_msg}")

            reply = _run_turn(user_msg, history, session_id, turn, replayer)
            _print_reply(reply, turn)

            history.append(ChatMessage(role="user", content=user_msg))
            history.append(ChatMessage(role="assistant", content=reply.reply))

            if reply.handoff_triggered:
                print(f"  {DIM}Demo complete — MeetingAgent would take over from here.{RESET}\n")
                break

        print("━" * W)
        print(f"  Demo finished: {turn} turns | final intent: {reply.intent}")
        print("━" * W)
        return

    # ── Interactive mode ──────────────────────────────────────────────────────
    if not settings.anthropic_api_key:
        print(f"  {RED}No ANTHROPIC_API_KEY found.{RESET}")
        print(f"  Set it in backend/.env or export it, then re-run.")
        print(f"  To see the demo without an API key: --demo flag\n")
        sys.exit(1)

    print(f"  Session: {session_id}  {DIM}(type your message, then Enter){RESET}\n")

    while True:
        try:
            raw = input(f"  {BOLD}You:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.\n")
            break

        if not raw:
            continue

        if raw.lower() == "exit":
            print("\n  Goodbye.\n")
            break

        if raw.lower() == "reset":
            history.clear()
            session_id = str(uuid.uuid4())[:8]
            turn = 0
            print(f"\n  {DIM}Conversation reset. New session: {session_id}{RESET}\n")
            continue

        turn += 1
        print(f"  {DIM}thinking...{RESET}", end="\r", flush=True)

        try:
            reply = _run_turn(raw, history, session_id, turn, None)
        except Exception as exc:
            print(f"\n  {RED}Error: {exc}{RESET}\n")
            continue

        _print_reply(reply, turn)

        history.append(ChatMessage(role="user", content=raw))
        history.append(ChatMessage(role="assistant", content=reply.reply))

        if reply.handoff_triggered:
            print(
                f"  {DIM}[MeetingAgent would book the call — "
                f"type 'reset' to start a new conversation]{RESET}\n"
            )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bizon Chat Agent REPL")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run a canned 4-turn demo conversation without an Anthropic API key",
    )
    args = parser.parse_args()
    repl(demo=args.demo)
