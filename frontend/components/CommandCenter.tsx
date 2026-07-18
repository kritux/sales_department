import StatCard from './StatCard'
import type { DailyReport } from '@/lib/types'

interface CommandCenterProps {
  report?: DailyReport | null
}

export default function CommandCenter({ report }: CommandCenterProps) {
  if (!report) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {['Leads found', 'Qualified', 'Emails sent', 'Calls made', 'Responses', 'Meetings'].map(l => (
          <StatCard key={l} label={l} value="—" />
        ))}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard label="Leads found"  value={report.leads_scraped}       accent="blue"    />
        <StatCard label="Qualified"    value={report.leads_qualified}      accent="tan"     />
        <StatCard label="Emails sent"  value={report.emails_sent}          accent="blue"    />
        <StatCard label="Calls made"   value={report.calls_made}           accent="tan"     />
        <StatCard label="Responses"    value={report.responses_received}   accent="success" />
        <StatCard label="Meetings"     value={report.meetings_booked}      accent="success" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <StatCard
          label="Pipeline value"
          value={`$${report.pipeline_value_usd.toLocaleString()}`}
          accent="success"
          sub={`${report.urgent_alerts_sent} urgent alert${report.urgent_alerts_sent !== 1 ? 's' : ''}`}
        />
        <StatCard
          label="Alerts"
          value={report.urgent_alerts_sent}
          accent={report.urgent_alerts_sent > 0 ? 'danger' : 'neutral'}
          sub={`WhatsApp ${report.whatsapp_sent ? 'sent' : 'pending'} · Call ${report.call_made ? 'made' : 'not made'}`}
        />
      </div>

      {report.summary_text && (
        <div
          className="rounded-lg p-4 bg-surface font-mono text-sm"
          style={{ border: '0.5px solid var(--border)' }}
        >
          <p className="text-2xs text-muted uppercase tracking-widest mb-2">Director summary</p>
          <p className="text-sm leading-relaxed">{report.summary_text}</p>
        </div>
      )}

      {report.agent_activity.length > 0 && (
        <div className="overflow-x-auto rounded-lg" style={{ border: '0.5px solid var(--border)' }}>
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="bg-surface" style={{ borderBottom: '0.5px solid var(--border)' }}>
                {['Agent', 'Done', 'Failed', 'Tokens', 'Cost'].map(h => (
                  <th key={h} className="text-left px-3 py-2 text-muted font-medium uppercase tracking-widest text-2xs">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.agent_activity.map((a, i) => (
                <tr
                  key={a.agent_name}
                  className="hover:bg-surface/60 transition-colors"
                  style={{ borderBottom: i < report.agent_activity.length - 1 ? '0.5px solid var(--border)' : undefined }}
                >
                  <td className="px-3 py-2 font-medium">{a.agent_name}</td>
                  <td className="px-3 py-2 text-bizon-success">{a.tasks_completed}</td>
                  <td className="px-3 py-2 text-bizon-danger">{a.tasks_failed}</td>
                  <td className="px-3 py-2 text-muted">{a.tokens_used.toLocaleString()}</td>
                  <td className="px-3 py-2 text-muted">${a.cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
