import Link from 'next/link'
import TenantCard from '@/components/TenantCard'
import type { TenantConfig } from '@/lib/types'

const MOCK_TENANTS: TenantConfig[] = [
  {
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
  },
  {
    tenant_id: 'tenant_002',
    company_name: 'Soldadura TX',
    timezone: 'America/Chicago',
    language: 'es',
    geo_radius_miles: 40,
    geo_center: 'San Antonio, TX',
    scraping_keywords: ['soldadura industrial san antonio'],
    lead_criteria: {
      min_rating: 3.0, min_reviews: 5, max_reviews: null,
      has_website: null, company_size: 'any',
      industries: ['Welder'], exclude_keywords: [],
    },
    sender_name: 'María González',
    sender_email: 'maria@soldaduratx.com',
    owner_whatsapp: '+15559876543',
    owner_name: 'María',
    urgent_alert_threshold_usd: 3000,
    rag_collection: 'rag_tenant_002',
    active: true,
    daily_contact_cap: 30,
  },
]

export default function TenantsPage() {
  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold tracking-tight">Tenants</h1>
          <p className="text-xs text-muted font-mono mt-0.5">
            {MOCK_TENANTS.filter(t => t.active).length} active · {MOCK_TENANTS.length} total
          </p>
        </div>
        <Link
          href="#"
          className="px-3 py-1.5 text-xs font-mono rounded-md text-white bg-bizon-blue hover:opacity-90 transition-opacity"
        >
          + New tenant
        </Link>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {MOCK_TENANTS.map(t => (
          <TenantCard
            key={t.tenant_id}
            tenant={t}
            leadsToday={t.tenant_id === 'tenant_001' ? 48 : 12}
            emailsToday={t.tenant_id === 'tenant_001' ? 28 : 8}
          />
        ))}
      </div>
    </div>
  )
}
