import Link from 'next/link'
import CommandCenter from '@/components/CommandCenter'
import type { DailyReport } from '@/lib/types'

interface Props {
  params: { id: string }
}

const MOCK_REPORTS: DailyReport[] = [
  {
    tenant_id: 'tenant_001',
    report_date: '2026-07-18',
    leads_scraped: 48, leads_qualified: 31, emails_sent: 28,
    calls_made: 6, responses_received: 4, meetings_booked: 2,
    pipeline_value_usd: 18400, urgent_alerts_sent: 1,
    agent_activity: [
      { agent_name: 'Scout',       tasks_completed: 3,  tasks_failed: 0, tokens_used: 12800, cost_usd: 0.0154 },
      { agent_name: 'Email Agent', tasks_completed: 28, tasks_failed: 1, tokens_used: 34200, cost_usd: 0.0411 },
      { agent_name: 'Call Agent',  tasks_completed: 6,  tasks_failed: 0, tokens_used: 8400,  cost_usd: 0.0101 },
      { agent_name: 'Director',    tasks_completed: 1,  tasks_failed: 0, tokens_used: 5600,  cost_usd: 0.0337 },
    ],
    top_leads: ['lead-042', 'lead-017', 'lead-058'],
    summary_text: 'Strong day — 31 qualified, 4 responses, 2 meetings. One urgent lead at $8 400. WhatsApp sent 5:02 PM.',
    whatsapp_sent: true,
    call_made: false,
  },
  {
    tenant_id: 'tenant_001',
    report_date: '2026-07-17',
    leads_scraped: 35, leads_qualified: 22, emails_sent: 20,
    calls_made: 3, responses_received: 2, meetings_booked: 1,
    pipeline_value_usd: 9200, urgent_alerts_sent: 0,
    agent_activity: [
      { agent_name: 'Scout',       tasks_completed: 2,  tasks_failed: 0, tokens_used: 9100,  cost_usd: 0.0109 },
      { agent_name: 'Email Agent', tasks_completed: 20, tasks_failed: 0, tokens_used: 24100, cost_usd: 0.0289 },
      { agent_name: 'Director',    tasks_completed: 1,  tasks_failed: 0, tokens_used: 4800,  cost_usd: 0.0288 },
    ],
    top_leads: ['lead-033', 'lead-021'],
    summary_text: 'Solid day — 22 qualified, 2 responses, 1 meeting booked. No urgent alerts. All systems nominal.',
    whatsapp_sent: true,
    call_made: false,
  },
]

export default function ReportsPage({ params }: Props) {
  const latest = MOCK_REPORTS[0]

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <div className="flex items-center gap-2 text-sm text-muted font-mono mb-1">
          <Link href={`/tenants/${params.id}`} className="hover:text-white transition-colors">
            {params.id}
          </Link>
          <span>/</span>
          <span>reports</span>
        </div>
        <h1 className="text-lg font-bold tracking-tight">Daily Reports</h1>
      </div>

      {/* Date selector */}
      <div className="flex gap-2">
        {MOCK_REPORTS.map((r, i) => (
          <button
            key={r.report_date}
            className="px-3 py-1.5 text-xs font-mono rounded-md transition-colors"
            style={{
              border: '0.5px solid var(--border)',
              background: i === 0 ? '#0295fd' : 'var(--surface)',
              color: i === 0 ? '#fff' : 'var(--text-muted)',
            }}
          >
            {r.report_date}
          </button>
        ))}
      </div>

      <CommandCenter report={latest} />
    </div>
  )
}
