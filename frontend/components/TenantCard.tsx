import Link from 'next/link'
import clsx from 'clsx'
import BizonAvatar from './BizonAvatar'
import type { TenantConfig } from '@/lib/types'

interface TenantCardProps {
  tenant: TenantConfig
  leadsToday?: number
  emailsToday?: number
}

export default function TenantCard({ tenant, leadsToday, emailsToday }: TenantCardProps) {
  return (
    <Link
      href={`/tenants/${tenant.tenant_id}`}
      className={clsx(
        'block rounded-lg p-4 bg-surface transition-colors duration-150',
        'hover:border-bizon-blue/40',
        !tenant.active && 'opacity-50',
      )}
      style={{ border: '0.5px solid var(--border)' }}
    >
      <div className="flex items-start gap-3">
        <BizonAvatar
          expression={tenant.active ? 'default_smile' : 'sleepy_half_closed'}
          size={40}
          rounded="md"
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm truncate">{tenant.company_name}</span>
            <span
              className={clsx(
                'flex-shrink-0 text-2xs font-mono px-1.5 py-0.5 rounded',
                tenant.active
                  ? 'text-bizon-success bg-bizon-success/10'
                  : 'text-muted bg-surface',
              )}
            >
              {tenant.active ? 'active' : 'paused'}
            </span>
          </div>
          <p className="text-xs text-muted mt-0.5 truncate">{tenant.geo_center}</p>
        </div>
      </div>

      <div
        className="mt-3 pt-3 grid grid-cols-2 gap-2 text-xs font-mono"
        style={{ borderTop: '0.5px solid var(--border)' }}
      >
        <div>
          <span className="text-muted block">Leads today</span>
          <span className="font-semibold" style={{ color: '#0295fd' }}>
            {leadsToday ?? '—'}
          </span>
        </div>
        <div>
          <span className="text-muted block">Emails sent</span>
          <span className="font-semibold" style={{ color: '#9e7a57' }}>
            {emailsToday ?? '—'}
          </span>
        </div>
      </div>

      <p className="mt-2 text-2xs text-muted font-mono truncate">
        {tenant.tenant_id} · {tenant.language.toUpperCase()} · cap {tenant.daily_contact_cap}/day
      </p>
    </Link>
  )
}
