export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-lg font-bold tracking-tight">Settings</h1>
        <p className="text-xs text-muted font-mono mt-0.5">Platform configuration</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SettingsSection title="Backend API">
          <SettingsRow
            label="API base URL"
            value={process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'}
            badge="env"
          />
          <SettingsRow label="DRY_RUN mode" value="true" badge="env" />
        </SettingsSection>

        <SettingsSection title="Supabase">
          <SettingsRow label="Project URL" value="Set via NEXT_PUBLIC_SUPABASE_URL" badge="env" />
          <SettingsRow label="Anon key"    value="Set via NEXT_PUBLIC_SUPABASE_ANON_KEY" badge="env" />
        </SettingsSection>

        <SettingsSection title="Scheduler">
          <SettingsRow label="Start time"  value="07:00 tenant timezone" />
          <SettingsRow label="End time"    value="17:00 tenant timezone" />
          <SettingsRow label="WhatsApp delay" value="15 min before voice call" />
        </SettingsSection>

        <SettingsSection title="Build phase">
          <SettingsRow label="Current phase"    value="Phase 4 — Frontend" badge="active" />
          <SettingsRow label="Backend status"   value="RAG + Agents ready" />
          <SettingsRow label="Frontend status"  value="Scaffold complete" />
          <SettingsRow label="Next phase"       value="Phase 5 — Multi-tenant deploy" />
        </SettingsSection>
      </div>

      <div
        className="rounded-lg p-4 bg-surface"
        style={{ border: '0.5px solid var(--border)' }}
      >
        <p className="text-xs font-mono text-muted uppercase tracking-widest mb-3">Environment variables required</p>
        <pre className="text-2xs font-mono text-muted leading-relaxed whitespace-pre-wrap">
{`NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`}
        </pre>
        <p className="text-2xs text-muted mt-2">Copy <code>.env.local.example</code> → <code>.env.local</code> and fill in values.</p>
      </div>
    </div>
  )
}

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-lg p-4 bg-surface flex flex-col gap-3"
      style={{ border: '0.5px solid var(--border)' }}
    >
      <h3 className="text-xs font-mono text-muted uppercase tracking-widest">{title}</h3>
      {children}
    </div>
  )
}

function SettingsRow({
  label,
  value,
  badge,
}: {
  label: string
  value: string
  badge?: 'env' | 'active'
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-xs text-muted font-mono shrink-0">{label}</span>
      <div className="flex items-center gap-1.5 min-w-0">
        {badge && (
          <span
            className="text-2xs font-mono px-1.5 py-0.5 rounded flex-shrink-0"
            style={{
              color: badge === 'active' ? '#2ecc8f' : '#0295fd',
              background: badge === 'active' ? 'rgba(46,204,143,0.1)' : 'rgba(2,149,253,0.1)',
              border: '0.5px solid var(--border)',
            }}
          >
            {badge}
          </span>
        )}
        <span className="text-xs font-mono truncate text-right">{value}</span>
      </div>
    </div>
  )
}
