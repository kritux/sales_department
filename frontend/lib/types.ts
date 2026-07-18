// Mirror of backend Pydantic contracts from TEAM.md

export type LeadStatus =
  | 'new'
  | 'contacted'
  | 'responded'
  | 'meeting_set'
  | 'closed_won'
  | 'closed_lost'
  | 'no_response'

export interface Lead {
  id: string
  tenant_id: string
  company_name: string
  address: string
  city: string
  state: string
  phone: string | null
  email: string | null
  website: string | null
  rating: number | null
  review_count: number | null
  category: string
  score: number
  source: 'google_maps' | 'yelp' | 'manual'
  status: LeadStatus
  last_contact_at: string | null
  notes: string
  created_at: string
  updated_at: string
}

export interface LeadCriteria {
  min_rating: number
  min_reviews: number
  max_reviews: number | null
  has_website: boolean | null
  company_size: 'any' | 'small' | 'medium' | 'large'
  industries: string[]
  exclude_keywords: string[]
}

export interface TenantConfig {
  tenant_id: string
  company_name: string
  timezone: string
  language: 'es' | 'en' | 'both'
  geo_radius_miles: number
  geo_center: string
  scraping_keywords: string[]
  lead_criteria: LeadCriteria
  sender_name: string
  sender_email: string
  owner_whatsapp: string
  owner_name: string
  urgent_alert_threshold_usd: number
  rag_collection: string
  active: boolean
  daily_contact_cap: number
}

export interface AgentActivity {
  agent_name: string
  tasks_completed: number
  tasks_failed: number
  tokens_used: number
  cost_usd: number
}

export interface DailyReport {
  tenant_id: string
  report_date: string
  leads_scraped: number
  leads_qualified: number
  emails_sent: number
  calls_made: number
  responses_received: number
  meetings_booked: number
  pipeline_value_usd: number
  urgent_alerts_sent: number
  agent_activity: AgentActivity[]
  top_leads: string[]
  summary_text: string
  whatsapp_sent: boolean
  call_made: boolean
}

export type SystemState = 'scanning' | 'success' | 'standby' | 'error'
