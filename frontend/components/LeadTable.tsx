'use client'

import { useState } from 'react'
import clsx from 'clsx'
import StatusDot from './StatusDot'
import type { Lead, LeadStatus } from '@/lib/types'

const ALL_STATUSES: LeadStatus[] = [
  'new', 'contacted', 'responded', 'meeting_set',
  'closed_won', 'closed_lost', 'no_response',
]

interface LeadTableProps {
  leads: Lead[]
}

export default function LeadTable({ leads }: LeadTableProps) {
  const [filter, setFilter] = useState<LeadStatus | 'all'>('all')
  const [sort, setSort] = useState<'score' | 'created_at'>('score')

  const visible = leads
    .filter(l => filter === 'all' || l.status === filter)
    .sort((a, b) =>
      sort === 'score'
        ? b.score - a.score
        : new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )

  return (
    <div className="flex flex-col gap-3">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 flex-wrap">
          {(['all', ...ALL_STATUSES] as const).map(s => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={clsx(
                'text-2xs font-mono px-2 py-1 rounded transition-colors',
                filter === s
                  ? 'bg-bizon-blue text-white'
                  : 'bg-surface text-muted hover:text-white',
              )}
              style={{ border: '0.5px solid var(--border)' }}
            >
              {s === 'all' ? 'All' : s.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1">
          {(['score', 'created_at'] as const).map(s => (
            <button
              key={s}
              onClick={() => setSort(s)}
              className={clsx(
                'text-2xs font-mono px-2 py-1 rounded transition-colors',
                sort === s
                  ? 'text-bizon-blue'
                  : 'text-muted hover:text-white',
              )}
              style={{ border: '0.5px solid var(--border)' }}
            >
              {s === 'score' ? 'Score' : 'Newest'}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg" style={{ border: '0.5px solid var(--border)' }}>
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="bg-surface" style={{ borderBottom: '0.5px solid var(--border)' }}>
              {['Company', 'Category', 'City', 'Score', 'Status', 'Last contact'].map(h => (
                <th
                  key={h}
                  className="text-left px-3 py-2 text-muted font-medium uppercase tracking-widest text-2xs"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-muted">
                  No leads match this filter.
                </td>
              </tr>
            )}
            {visible.map((lead, i) => (
              <tr
                key={lead.id}
                className={clsx(
                  'transition-colors hover:bg-surface/60',
                  i < visible.length - 1 && 'border-b-[0.5px]',
                )}
                style={{ borderColor: 'var(--border)' }}
              >
                <td className="px-3 py-2.5">
                  <div className="font-semibold truncate max-w-[160px]">{lead.company_name}</div>
                  {lead.email && (
                    <div className="text-muted text-2xs truncate max-w-[160px]">{lead.email}</div>
                  )}
                </td>
                <td className="px-3 py-2.5 text-muted truncate max-w-[120px]">{lead.category}</td>
                <td className="px-3 py-2.5 text-muted whitespace-nowrap">{lead.city}, {lead.state}</td>
                <td className="px-3 py-2.5">
                  <span
                    className={clsx(
                      'font-bold',
                      lead.score >= 80 ? 'text-bizon-success'
                        : lead.score >= 50 ? 'text-bizon-blue'
                        : 'text-muted',
                    )}
                  >
                    {lead.score}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <StatusDot status={lead.status} showLabel />
                </td>
                <td className="px-3 py-2.5 text-muted whitespace-nowrap">
                  {lead.last_contact_at
                    ? new Date(lead.last_contact_at).toLocaleDateString()
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-2xs text-muted text-right font-mono">
        {visible.length} of {leads.length} leads
      </p>
    </div>
  )
}
