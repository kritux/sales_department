import Link from 'next/link'
import LeadTable from '@/components/LeadTable'
import type { Lead } from '@/lib/types'

const MOCK_LEADS: Lead[] = [
  {
    id: 'lead-001', tenant_id: 'tenant_001',
    company_name: 'Acme Contractors', address: '123 Main St', city: 'Houston', state: 'TX',
    phone: '+17135550001', email: 'owner@acme.com', website: null,
    rating: 4.5, review_count: 23, category: 'General Contractor',
    score: 88, source: 'google_maps', status: 'contacted',
    last_contact_at: '2026-07-17T10:30:00', notes: '', created_at: '2026-07-18T07:00:00', updated_at: '2026-07-18T07:00:00',
  },
  {
    id: 'lead-002', tenant_id: 'tenant_001',
    company_name: 'TexBuild LLC', address: '456 Oak Ave', city: 'Houston', state: 'TX',
    phone: '+17135550002', email: null, website: null,
    rating: 4.0, review_count: 11, category: 'Roofer',
    score: 74, source: 'google_maps', status: 'new',
    last_contact_at: null, notes: '', created_at: '2026-07-18T07:15:00', updated_at: '2026-07-18T07:15:00',
  },
  {
    id: 'lead-003', tenant_id: 'tenant_001',
    company_name: 'Gulf Coast Plumbing', address: '789 Bayou Blvd', city: 'Pasadena', state: 'TX',
    phone: '+17135550003', email: 'info@gcplumb.com', website: null,
    rating: 3.8, review_count: 17, category: 'Plumber',
    score: 62, source: 'google_maps', status: 'responded',
    last_contact_at: '2026-07-16T14:20:00', notes: '', created_at: '2026-07-15T07:00:00', updated_at: '2026-07-16T14:20:00',
  },
  {
    id: 'lead-004', tenant_id: 'tenant_001',
    company_name: 'Lone Star Electric', address: '321 Prairie Rd', city: 'Sugar Land', state: 'TX',
    phone: '+17135550004', email: 'ls@electric.com', website: null,
    rating: 4.2, review_count: 34, category: 'Electrician',
    score: 91, source: 'google_maps', status: 'meeting_set',
    last_contact_at: '2026-07-17T09:00:00', notes: '', created_at: '2026-07-14T07:00:00', updated_at: '2026-07-17T09:00:00',
  },
  {
    id: 'lead-005', tenant_id: 'tenant_001',
    company_name: 'Harris County HVAC', address: '654 AC Way', city: 'Katy', state: 'TX',
    phone: null, email: 'hvac@harris.com', website: null,
    rating: 3.5, review_count: 12, category: 'HVAC',
    score: 55, source: 'google_maps', status: 'no_response',
    last_contact_at: '2026-06-10T08:00:00', notes: '', created_at: '2026-06-08T07:00:00', updated_at: '2026-06-10T08:00:00',
  },
]

interface Props {
  params: { id: string }
}

export default function LeadsPage({ params }: Props) {
  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm text-muted font-mono mb-1">
            <Link href={`/tenants/${params.id}`} className="hover:text-white transition-colors">
              {params.id}
            </Link>
            <span>/</span>
            <span>leads</span>
          </div>
          <h1 className="text-lg font-bold tracking-tight">Leads</h1>
        </div>
        <p className="text-xs text-muted font-mono">{MOCK_LEADS.length} total</p>
      </div>

      <LeadTable leads={MOCK_LEADS} />
    </div>
  )
}
