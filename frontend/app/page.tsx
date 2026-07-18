import BizonNetworkHero from '@/components/BizonNetworkHero'
import CommandCenter from '@/components/CommandCenter'
import type { DailyReport, SystemState } from '@/lib/types'

const MOCK_STATE: SystemState = 'standby'

const MOCK_TENANTS = [
  { id: 'tenant_001', name: 'Growth Bizon' },
  { id: 'tenant_002', name: 'Soldadura TX' },
  { id: 'tenant_003', name: 'Plumber Co.' },
]

const MOCK_REPORT: DailyReport = {
  tenant_id: 'tenant_001',
  report_date: '2026-07-18',
  leads_scraped: 48,
  leads_qualified: 31,
  emails_sent: 28,
  calls_made: 6,
  responses_received: 4,
  meetings_booked: 2,
  pipeline_value_usd: 18400,
  urgent_alerts_sent: 1,
  agent_activity: [
    { agent_name: 'Scout',        tasks_completed: 3, tasks_failed: 0, tokens_used: 12800, cost_usd: 0.0154 },
    { agent_name: 'Email Agent',  tasks_completed: 28, tasks_failed: 1, tokens_used: 34200, cost_usd: 0.0411 },
    { agent_name: 'Call Agent',   tasks_completed: 6, tasks_failed: 0, tokens_used: 8400, cost_usd: 0.0101 },
    { agent_name: 'Director',     tasks_completed: 1, tasks_failed: 0, tokens_used: 5600, cost_usd: 0.0337 },
  ],
  top_leads: ['lead-042', 'lead-017', 'lead-058'],
  summary_text:
    'Strong day — 31 qualified leads, 4 responses, 2 meetings booked. One urgent lead flagged at $8 400 potential. ' +
    'WhatsApp summary delivered at 5:02 PM. Email open rate 14.3%.',
  whatsapp_sent: true,
  call_made: false,
}

export default function HomePage() {
  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-lg font-bold tracking-tight">Command Center</h1>
        <p className="text-xs text-muted font-mono mt-0.5">
          {new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
        </p>
      </div>

      <BizonNetworkHero state={MOCK_STATE} tenants={MOCK_TENANTS} />

      <div>
        <h2 className="text-sm font-semibold mb-3" style={{ color: '#0295fd' }}>
          Today&apos;s Performance — Growth Bizon
        </h2>
        <CommandCenter report={MOCK_REPORT} />
      </div>
    </div>
  )
}
