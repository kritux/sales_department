'use client'

import { useState } from 'react'
import Link from 'next/link'
import clsx from 'clsx'
import dynamic from 'next/dynamic'
import BizonAvatar from '@/components/BizonAvatar'
import StatusDot from '@/components/StatusDot'
import { getTenantStats, type TimeRange, type FunnelStage, type RecentLead } from '@/lib/tenant-data'
import type { AgentActivity, LeadStatus } from '@/lib/types'

// Recharts must be client-only; dynamic import with ssr:false keeps the build clean
const TrendChart = dynamic(() => import('@/components/TrendChart'), { ssr: false })

// ─── Mock tenant meta (Phase 5: fetch from Supabase tenants table) ─────────────

const MOCK_META: Record<string, { name: string; active: boolean; plan: string; geo: string }> = {
  tenant_001: { name: 'Growth Bizon',  active: true,  plan: 'Pro',    geo: 'Houston, TX'     },
  tenant_002: { name: 'Soldadura TX',  active: true,  plan: 'Starter',geo: 'San Antonio, TX' },
  tenant_003: { name: 'Plumber Co.',   active: false, plan: 'Pro',    geo: 'Dallas, TX'      },
}
const FALLBACK_META = { name: 'Tenant', active: true, plan: '—', geo: '—' }

// ─── Range config ──────────────────────────────────────────────────────────────

const RANGES: { key: TimeRange; label: string }[] = [
  { key: '1d',  label: 'Today'  },
  { key: '7d',  label: '7 days' },
  { key: '30d', label: '30 days' },
]

// ─── Sub-page links ────────────────────────────────────────────────────────────

const SUB_PAGES = [
  { href: 'leads',   label: 'Leads'    },
  { href: 'rag',     label: 'RAG docs' },
  { href: 'reports', label: 'Reports'  },
]

// ─── Color helpers ─────────────────────────────────────────────────────────────

function pctColor(pct: number): string {
  if (pct >= 80) return '#2ecc8f'
  if (pct >= 50) return '#0295fd'
  if (pct >= 20) return '#9e7a57'
  return '#ff4d4d'
}

function scoreColor(score: number): string {
  if (score >= 80) return '#2ecc8f'
  if (score >= 60) return '#0295fd'
  return 'var(--text-muted)'
}

// ─── Page ──────────────────────────────────────────────────────────────────────

interface Props {
  params: { id: string }
}

export default function TenantStatsPage({ params }: Props) {
  const [range, setRange] = useState<TimeRange>('1d')
  const [sortDesc, setSortDesc] = useState(true)

  const meta   = MOCK_META[params.id] ?? FALLBACK_META
  const stats  = getTenantStats(params.id, range)
  const leads  = [...stats.recent_leads].sort((a, b) => sortDesc ? b.score - a.score : a.score - b.score)
  const maxFunnel = stats.funnel[0]?.count ?? 1

  return (
    <div className="flex flex-col gap-6 p-6 pb-12">

      {/* ── 1. Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <BizonAvatar
            expression={meta.active ? 'content_smile_teeth' : 'sleepy_half_closed'}
            size={48}
            rounded="md"
            priority
          />
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-lg font-bold tracking-tight">{meta.name}</h1>
              <span
                className="text-2xs font-mono px-1.5 py-0.5 rounded"
                style={{
                  color:       meta.active ? '#2ecc8f' : 'var(--text-muted)',
                  background:  meta.active ? 'rgba(46,204,143,0.1)' : 'var(--surface)',
                  border:      '0.5px solid var(--border)',
                }}
              >
                {meta.active ? 'active' : 'paused'}
              </span>
              <span
                className="text-2xs font-mono px-1.5 py-0.5 rounded"
                style={{ color: '#0295fd', background: 'rgba(2,149,253,0.08)', border: '0.5px solid var(--border)' }}
              >
                {meta.plan}
              </span>
            </div>
            <p className="text-xs text-muted font-mono mt-0.5">
              {params.id} · {meta.geo}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          {SUB_PAGES.map(sp => (
            <Link
              key={sp.href}
              href={`/tenants/${params.id}/${sp.href}`}
              className="px-3 py-1.5 text-xs font-mono rounded-md text-muted hover:text-white transition-colors"
              style={{ border: '0.5px solid var(--border)' }}
            >
              {sp.label}
            </Link>
          ))}
        </div>
      </div>

      {/* ── 2. Time range selector ─────────────────────────────────────────── */}
      <div className="flex gap-1.5">
        {RANGES.map(r => (
          <button
            key={r.key}
            onClick={() => setRange(r.key)}
            className="px-4 py-1.5 text-xs font-mono rounded-md transition-colors"
            style={{
              border:      '0.5px solid var(--border)',
              background:  range === r.key ? '#0295fd' : 'var(--surface)',
              color:       range === r.key ? '#fff'    : 'var(--text-muted)',
            }}
          >
            {r.label}
          </button>
        ))}
      </div>

      {/* ── 3. Funnel breakdown ────────────────────────────────────────────── */}
      <Section title="Funnel">
        <div className="flex flex-col gap-2">
          {stats.funnel.map((stage, i) => (
            <FunnelRow key={stage.key} stage={stage} max={maxFunnel} index={i} />
          ))}
        </div>
      </Section>

      {/* ── 4. Trend chart ────────────────────────────────────────────────── */}
      <Section
        title="Trend"
        right={
          <span className="flex items-center gap-3 text-2xs font-mono text-muted">
            <LegendDot color="#0295fd" label="Leads"     />
            <LegendDot color="#9e7a57" label="Emails"    />
            <LegendDot color="#2ecc8f" label="Responses" />
          </span>
        }
      >
        <TrendChart data={stats.trend} height={200} />
      </Section>

      {/* ── 5. Lead cadence health ────────────────────────────────────────── */}
      <Section title="Active cadence pipeline">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {stats.cadence.map(step => {
            const total = stats.cadence.reduce((s, c) => s + c.count, 0)
            const pct   = total > 0 ? step.count / total : 0
            return (
              <div
                key={step.key}
                className="rounded-lg p-3 bg-surface flex flex-col gap-2"
                style={{ border: '0.5px solid var(--border)' }}
              >
                <div>
                  <p className="text-2xs font-mono text-muted uppercase tracking-widest">Day {step.day}</p>
                  <p className="text-xs font-medium mt-0.5">{step.label}</p>
                </div>
                <div className="flex items-end gap-2">
                  <span className="text-xl font-bold" style={{ color: '#0295fd' }}>{step.count}</span>
                  <span className="text-2xs text-muted font-mono mb-0.5">leads</span>
                </div>
                {/* mini bar */}
                <div
                  className="h-0.5 rounded-full"
                  style={{ background: 'var(--border)', position: 'relative' }}
                >
                  <div
                    className="h-full rounded-full absolute left-0 top-0"
                    style={{
                      width:      `${Math.round(pct * 100)}%`,
                      background: '#0295fd',
                      transition: 'width 0.4s ease',
                    }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </Section>

      {/* ── 6. Recent leads table ─────────────────────────────────────────── */}
      <Section title="Recent leads">
        <div className="overflow-x-auto rounded-lg" style={{ border: '0.5px solid var(--border)' }}>
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="bg-surface" style={{ borderBottom: '0.5px solid var(--border)' }}>
                <Th>Company</Th>
                <Th>
                  <button
                    className="flex items-center gap-1 hover:text-white transition-colors"
                    onClick={() => setSortDesc(d => !d)}
                  >
                    Score {sortDesc ? '↓' : '↑'}
                  </button>
                </Th>
                <Th>Status</Th>
                <Th>Last contact</Th>
                <Th>Next action</Th>
              </tr>
            </thead>
            <tbody>
              {leads.map((lead, i) => (
                <tr
                  key={lead.id}
                  className="hover:bg-surface/60 transition-colors"
                  style={{ borderBottom: i < leads.length - 1 ? '0.5px solid var(--border)' : undefined }}
                >
                  <td className="px-3 py-2.5 font-medium">{lead.company_name}</td>
                  <td className="px-3 py-2.5">
                    <span className="font-bold" style={{ color: scoreColor(lead.score) }}>
                      {lead.score}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusDot status={lead.status} showLabel />
                  </td>
                  <td className="px-3 py-2.5 text-muted whitespace-nowrap">
                    {lead.last_contact_at ?? '—'}
                  </td>
                  <td className="px-3 py-2.5 text-muted max-w-[200px] truncate">
                    {lead.next_action ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {/* ── 7. Cost breakdown ─────────────────────────────────────────────── */}
      <Section
        title={`Cost breakdown — ${params.id}`}
        right={
          <span className="text-xs font-mono text-muted">
            Total:{' '}
            <span style={{ color: '#2ecc8f' }}>${stats.total_cost_usd.toFixed(4)}</span>
          </span>
        }
      >
        <div className="overflow-x-auto rounded-lg" style={{ border: '0.5px solid var(--border)' }}>
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="bg-surface" style={{ borderBottom: '0.5px solid var(--border)' }}>
                {['Agent', 'Done', 'Failed', 'Tokens', 'Cost'].map(h => (
                  <Th key={h}>{h}</Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stats.agent_activity.map((a, i) => (
                <tr
                  key={a.agent_name}
                  className="hover:bg-surface/60 transition-colors"
                  style={{ borderBottom: i < stats.agent_activity.length - 1 ? '0.5px solid var(--border)' : undefined }}
                >
                  <td className="px-3 py-2.5 font-medium">{a.agent_name}</td>
                  <td className="px-3 py-2.5" style={{ color: '#2ecc8f' }}>{a.tasks_completed}</td>
                  <td className="px-3 py-2.5" style={{ color: a.tasks_failed > 0 ? '#ff4d4d' : 'var(--text-muted)' }}>
                    {a.tasks_failed}
                  </td>
                  <td className="px-3 py-2.5 text-muted">{a.tokens_used.toLocaleString()}</td>
                  <td className="px-3 py-2.5 text-muted">${a.cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function Section({
  title,
  right,
  children,
}: {
  title: string
  right?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-2xs font-mono text-muted uppercase tracking-widest">{title}</p>
        {right}
      </div>
      {children}
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="text-left px-3 py-2 text-muted font-medium uppercase tracking-widest text-2xs">
      {children}
    </th>
  )
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="w-2 h-2 rounded-full inline-block" style={{ background: color }} />
      {label}
    </span>
  )
}

function FunnelRow({ stage, max, index }: { stage: FunnelStage; max: number; index: number }) {
  const widthPct = max > 0 ? (stage.count / max) * 100 : 0
  // Opacity steps: 1.0 → 0.82 → 0.66 → 0.50 → 0.36 → 0.24
  const barOpacity = Math.max(0.22, 1 - index * 0.16)

  return (
    <div className="flex items-center gap-3">
      {/* Stage label */}
      <span className="text-2xs font-mono text-muted uppercase tracking-wider w-24 shrink-0 text-right">
        {stage.label}
      </span>

      {/* Bar track */}
      <div className="flex-1 h-5 rounded relative" style={{ background: 'var(--surface)', border: '0.5px solid var(--border)' }}>
        <div
          className="h-full rounded"
          style={{
            width:      `${widthPct}%`,
            background: `rgba(2,149,253,${barOpacity})`,
            transition: 'width 0.45s ease',
          }}
        />
      </div>

      {/* Count */}
      <span
        className="text-sm font-bold w-12 text-right shrink-0"
        style={{ color: '#0295fd' }}
      >
        {stage.count.toLocaleString()}
      </span>

      {/* Conversion */}
      <span
        className="text-2xs font-mono w-14 shrink-0"
        style={{ color: stage.pct !== null ? pctColor(stage.pct) : 'transparent' }}
      >
        {stage.pct !== null ? `↓ ${stage.pct}%` : '—'}
      </span>
    </div>
  )
}
