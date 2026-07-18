interface StatCardProps {
  label: string
  value: string | number
  sub?: string
  accent?: 'blue' | 'tan' | 'success' | 'danger' | 'neutral'
}

const ACCENT_COLORS = {
  blue:    '#0295fd',
  tan:     '#9e7a57',
  success: '#2ecc8f',
  danger:  '#ff4d4d',
  neutral: 'var(--text-muted)',
}

export default function StatCard({ label, value, sub, accent = 'neutral' }: StatCardProps) {
  return (
    <div
      className="bg-surface rounded-lg p-4 flex flex-col gap-1"
      style={{ border: '0.5px solid var(--border)' }}
    >
      <span className="text-xs font-mono text-muted uppercase tracking-widest">{label}</span>
      <span
        className="text-2xl font-bold leading-none"
        style={{ color: ACCENT_COLORS[accent] }}
      >
        {value}
      </span>
      {sub && <span className="text-xs text-muted">{sub}</span>}
    </div>
  )
}
