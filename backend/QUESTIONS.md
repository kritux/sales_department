# Security & QA Report — Phase 1–4 Gate

> Generated after Comms Engineer session (chat_agent + chat_api + API stubs).
> Per AGENTS.md: "Output a security report: list of ✅ passed / ❌ failed checks."

---

## Security Checklist (AGENTS.md §Security & QA)

| # | Check | Result | File:Line |
|---|-------|--------|-----------|
| 1 | No hardcoded secrets — all loaded via `settings.py` | ✅ | `config/settings.py` |
| 2 | `.env` in `.gitignore`, never committed | ✅ | `.gitignore` |
| 3 | All FastAPI endpoints have auth middleware | ✅ | `api/chat.py`, `api/tenants.py`, `api/leads.py`, `api/rag.py`, `api/reports.py` — all use `Depends(_require_auth)` |
| 4 | Every Supabase query filters by `tenant_id` | N/A | Supabase not wired yet (Phase 5). Stubs raise 503. Will enforce on integration. |
| 5 | ChromaDB always uses `f"rag_{tenant_id}"` | ✅ | `tools/rag_loader.py`, `tools/rag_query.py`, `api/rag.py:status` |
| 6 | Rate limiting in `maps_scraper.py` | ✅ | `tools/maps_scraper.py` — `time.sleep(random.uniform(2, 5))` between requests |
| 7 | DRY_RUN gate in email/whatsapp/call tools | ✅ | `tools/email_tool.py:266`, `tools/whatsapp_tool.py:187`, `tools/call_tool.py:294` |
| 8 | No PII logged beyond `{email_domain, first_name}` | ✅ FIXED | See fixes below |

All checks passing. ✅ Zero ❌.

---

## Fixes Applied This Session

### Check 8 — PII Logging (was ❌, now ✅)

**Problem:** Three tools were logging full PII in both dry-run and production paths:

| File | Line | Was | Fixed To |
|------|------|-----|----------|
| `tools/email_tool.py` | 268, 271, 272, 293 | Full email address (`john@example.com`) | Domain only (`@example.com`) via `_email_domain()` |
| `tools/whatsapp_tool.py` | 189, 213 | Full phone number (`+15551234567`) | Masked (`+***4567`) via `_mask_phone()` |
| `tools/call_tool.py` | 296, 317 | Full phone number (`+15551234567`) | Masked (`+***4567`) via `_mask_phone()` |

**Helpers added:**
- `email_tool.py`: `_email_domain(addr)` — strips local part, returns `@domain.com`
- `whatsapp_tool.py`, `call_tool.py`: `_mask_phone(number)` — returns `+***{last4}`

---

## Test Coverage (AGENTS.md requirements)

| File | Requirement | Status |
|------|-------------|--------|
| `tests/test_scraper.py` | Scrape runs, filter works, dry_run blocks DB write | ✅ 35 tests |
| `tests/test_rag.py` | Load docs, query returns results, cross-tenant isolation | ✅ 40 tests |
| `tests/test_comms.py` | dry_run logs but doesn't send, templates render correctly | ✅ 102 tests |
| `tests/test_director.py` | Daily run sequence, timezone correctness | ✅ 73 tests |
| `tests/test_api.py` | All endpoints 401 without auth, 200/503 with valid token | ✅ 39 tests (NEW) |
| `tests/test_chat_agent.py` | ChatAgent unit tests (intent, RAG, model selection) | ✅ 59 tests |
| `tests/test_chat_api.py` | Chat API 401/200/422/503/500 paths | ✅ 28 tests |

**Total suite:** 666 tests, 0 failures, 0 errors.

---

## New Files This Session

| File | Purpose |
|------|---------|
| `api/tenants.py` | GET/POST/PUT tenant CRUD — auth gated, 503 until Phase 5 |
| `api/leads.py` | GET/PATCH lead management — auth gated, status validation, 503 until Phase 5 |
| `api/rag.py` | POST upload + GET status — auth gated, file-type validation, wraps `rag_loader` |
| `api/reports.py` | GET daily + history — auth gated, defines Contract 4 `DailyReport` model (TEAM.md) |
| `main.py` | FastAPI entrypoint, mounts all routers under `/api/v1`, health probe at `/` |
| `tests/test_api.py` | 39 tests — auth guard + handler reachability across all routers |

---

## Open Items (Phase 5)

- [ ] Supabase JWT validation in `_require_auth` (currently accept any Bearer token)
- [ ] `_load_tenant` / `_list_tenants` wired to real Supabase RLS queries
- [ ] Lead CRUD stubbed to Supabase `leads` table with `tenant_id` filter
- [ ] Report queries against `daily_reports` table
- [ ] Multi-tenant RLS policies enforced at DB level

None of these block Phase 1–4 functionality. All stubs return clear 503 messages.
