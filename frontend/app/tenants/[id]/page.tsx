import Link from 'next/link'
import LeadProfileBuilder from '@/components/LeadProfileBuilder'
import type { TenantConfig } from '@/lib/types'

const MOCK_TENANT: TenantConfig = {
  tenant_id: 'tenant_001',
  company_name: 'Growth Bizon',
  timezone: 'America/Chicago',
  language: 'en',
  geo_radius_miles: 50,
  geo_center: 'Houston, TX',
  scraping_keywords: ['contractor no website Houston'],
  lead_criteria: {
    min_rating: 3.5, min_reviews: 10, max_reviews: null,
    has_website: false, company_size: 'small',
    industries: ['General Contractor'], exclude_keywords: [],
  },
  sender_name: 'Carlos Rodriguez',
  sender_email: 'carlos@growthbizon.com',
  owner_whatsapp: '+15551234567',
  owner_name: 'Carlos',
  urgent_alert_threshold_usd: 5000,
  rag_collection: 'rag_tenant_001',
  active: true,
  daily_contact_cap: 50,
}

interface Props {
  params: { id: string }
}

const SUB_PAGES = [
  { href: 'leads',   label: 'Leads'   },
  { href: 'rag',     label: 'RAG docs' },
  { href: 'reports', label: 'Reports' },
]

export default function TenantDetailPage({ params }: Props) {
  const t = MOCK_TENANT

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold tracking-tight">{t.company_name}</h1>
            <span
              className="text-2xs font-mono px-1.5 py-0.5 rounded"
              style={{
                color: t.active ? '#2ecc8f' : 'var(--text-muted)',
                background: t.active ? 'rgba(46,204,143,0.1)' : 'var(--surface)',
                border: '0.5px solid var(--border)',
              }}
            >
              {t.active ? 'active' : 'paused'}
            </span>
          </div>
          <p className="text-xs text-muted font-mono mt-0.5">{params.id}</p>
        </div>
        <div className="flex gap-2">
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

      {/* Config grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ConfigSection title="Identity">
          <ConfigRow label="Sender name"  value={t.sender_name} />
          <ConfigRow label="Sender email" value={t.sender_email} />
          <ConfigRow label="Owner"        value={t.owner_name} />
          <ConfigRow label="WhatsApp"     value={t.owner_whatsapp} />
          <ConfigRow label="Language"     value={t.language.toUpperCase()} />
        </ConfigSection>

        <ConfigSection title="Geography">
          <ConfigRow label="Geo center"   value={t.geo_center} />
          <ConfigRow label="Radius"       value={`${t.geo_radius_miles} miles`} />
          <ConfigRow label="Timezone"     value={t.timezone} />
          <ConfigRow label="Daily cap"    value={`${t.daily_contact_cap} contacts`} />
          <ConfigRow label="Alert thresh" value={`$${t.urgent_alert_threshold_usd.toLocaleString()}`} />
        </ConfigSection>
      </div>

      {/* Keywords */}
      <ConfigSection title="Scraping keywords">
        <div className="flex flex-wrap gap-1.5">
          {t.scraping_keywords.map(kw => (
            <span
              key={kw}
              className="text-2xs font-mono px-2 py-0.5 rounded text-muted"
              style={{ border: '0.5px solid var(--border)', background: 'var(--surface)' }}
            >
              {kw}
            </span>
          ))}
        </div>
      </ConfigSection>

      {/* Lead profile builder */}
      <ConfigSection title="Lead criteria">
        <LeadProfileBuilder initial={t.lead_criteria} />
      </ConfigSection>
    </div>
  )
}

function ConfigSection({ title, children }: { title: string; children: React.ReactNode }) {
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

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-xs text-muted font-mono shrink-0">{label}</span>
      <span className="text-xs font-mono text-right truncate">{value}</span>
    </div>
  )
}
