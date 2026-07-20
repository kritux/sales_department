/**
 * Tenant statistics data layer.
 *
 * Currently returns deterministic mock data.
 * Phase 5 swap: replace each `getMock*` call body with a Supabase query
 * filtered by tenant_id — function signatures stay identical.
 */

import type { AgentActivity, LeadStatus } from './types'

// ─── Public types ─────────────────────────────────────────────────────────────

export type TimeRange = '1d' | '7d' | '30d'

export interface FunnelStage {
  key: string
  label: string
  count: number
  /** Conversion % from previous stage. null for the first stage. */
  pct: number | null
}

export interface TrendPoint {
  date: string
  leads: number
  emails: number
  responses: number
}

export interface CadenceStep {
  key: string
  label: string
  day: number
  count: number
}

export interface RecentLead {
  id: string
  company_name: string
  score: number
  status: LeadStatus
  last_contact_at: string | null
  next_action: string | null
}

export interface TenantStats {
  funnel: FunnelStage[]
  trend: TrendPoint[]
  cadence: CadenceStep[]
  recent_leads: RecentLead[]
  agent_activity: AgentActivity[]
  total_cost_usd: number
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Phase 5: replace body with Supabase queries for leads, outbound_messages,
 * and daily_reports tables, all filtered by tenant_id.
 */
export function getTenantStats(_tenantId: string, range: TimeRange): TenantStats {
  return {
    funnel:          getMockFunnel(range),
    trend:           getMockTrend(range),
    cadence:         MOCK_CADENCE,
    recent_leads:    MOCK_RECENT_LEADS,
    agent_activity:  MOCK_AGENT_ACTIVITY,
    total_cost_usd:  MOCK_AGENT_ACTIVITY.reduce((s, a) => s + a.cost_usd, 0),
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function buildFunnel(raw: number[]): FunnelStage[] {
  const LABELS = ['Leads found', 'Qualified', 'Contacted', 'Responded', 'Meetings', 'Closed won']
  return raw.map((count, i) => ({
    key:   LABELS[i].toLowerCase().replace(/\s+/g, '_'),
    label: LABELS[i],
    count,
    pct:   i === 0 ? null : raw[i - 1] > 0 ? Math.round(count / raw[i - 1] * 1000) / 10 : null,
  }))
}

function getMockFunnel(range: TimeRange): FunnelStage[] {
  const data: Record<TimeRange, number[]> = {
    '1d':  [48,  31,  28,  4,   2,   1  ],
    '7d':  [298, 194, 175, 26,  11,  5  ],
    '30d': [1243, 817, 728, 108, 44,  18 ],
  }
  return buildFunnel(data[range])
}

// Deterministic daily lead/email/response values (indexed by offset from today)
const DAILY_LEADS    = [48, 35, 43, 39, 46, 52, 31, 44, 38, 51, 29, 47, 36, 42, 55, 33, 48, 41, 37, 50, 28, 45, 39, 53, 44, 36, 49, 41, 38, 52]
const TODAY_HOURLY: TrendPoint[] = [
  { date: '7 AM',  leads: 6,  emails: 0,  responses: 0 },
  { date: '8 AM',  leads: 9,  emails: 6,  responses: 0 },
  { date: '9 AM',  leads: 11, emails: 8,  responses: 1 },
  { date: '10 AM', leads: 8,  emails: 6,  responses: 1 },
  { date: '11 AM', leads: 7,  emails: 5,  responses: 1 },
  { date: '12 PM', leads: 3,  emails: 2,  responses: 0 },
  { date: '1 PM',  leads: 6,  emails: 4,  responses: 1 },
  { date: '2 PM',  leads: 5,  emails: 4,  responses: 1 },
  { date: '3 PM',  leads: 3,  emails: 2,  responses: 0 },
  { date: '4 PM',  leads: 2,  emails: 1,  responses: 0 },
]

function getMockTrend(range: TimeRange): TrendPoint[] {
  if (range === '1d') return TODAY_HOURLY

  const days = range === '7d' ? 7 : 30
  const anchor = new Date(2026, 6, 20) // July 20 2026
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(anchor)
    d.setDate(d.getDate() - (days - 1 - i))
    const leads = DAILY_LEADS[i % DAILY_LEADS.length]
    return {
      date:      `${d.getMonth() + 1}/${d.getDate()}`,
      leads,
      emails:    Math.round(leads * 0.61),
      responses: Math.max(0, Math.round(leads * 0.08)),
    }
  })
}

// ─── Static mock data ─────────────────────────────────────────────────────────

const MOCK_CADENCE: CadenceStep[] = [
  { key: 'day_0',  label: 'Intro email',  day: 0,  count: 14 },
  { key: 'day_3',  label: 'Value email',  day: 3,  count: 9  },
  { key: 'day_7',  label: 'Call',         day: 7,  count: 5  },
  { key: 'day_14', label: 'Final email',  day: 14, count: 3  },
]

const MOCK_RECENT_LEADS: RecentLead[] = [
  {
    id: 'lead-004', company_name: 'Lone Star Electric',   score: 91,
    status: 'meeting_set',  last_contact_at: '2026-07-17', next_action: 'Meeting confirmed 7/22 2 PM',
  },
  {
    id: 'lead-001', company_name: 'Acme Contractors',     score: 88,
    status: 'contacted',    last_contact_at: '2026-07-18', next_action: 'Value email due 7/21',
  },
  {
    id: 'lead-003', company_name: 'Gulf Coast Plumbing',  score: 74,
    status: 'responded',    last_contact_at: '2026-07-16', next_action: 'Schedule call',
  },
  {
    id: 'lead-002', company_name: 'TexBuild LLC',         score: 74,
    status: 'new',          last_contact_at: null,          next_action: 'Intro email pending',
  },
  {
    id: 'lead-007', company_name: 'Bayou Roofing Co.',    score: 68,
    status: 'contacted',    last_contact_at: '2026-07-17', next_action: 'Call on day 7 (7/24)',
  },
  {
    id: 'lead-005', company_name: 'Harris County HVAC',   score: 55,
    status: 'no_response',  last_contact_at: '2026-06-10', next_action: 'WinBack in 21 days',
  },
]

const MOCK_AGENT_ACTIVITY: AgentActivity[] = [
  { agent_name: 'Scout',       tasks_completed: 3,  tasks_failed: 0, tokens_used: 12800, cost_usd: 0.0154 },
  { agent_name: 'Email Agent', tasks_completed: 28, tasks_failed: 1, tokens_used: 34200, cost_usd: 0.0411 },
  { agent_name: 'Call Agent',  tasks_completed: 6,  tasks_failed: 0, tokens_used:  8400, cost_usd: 0.0101 },
  { agent_name: 'Director',    tasks_completed: 1,  tasks_failed: 0, tokens_used:  5600, cost_usd: 0.0337 },
]
