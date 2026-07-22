'use client'

import { useState } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? ''

interface Props {
  onClose: () => void
  onCreated: () => void
}

interface FormState {
  tenant_id: string
  company_name: string
  geo_center: string
  geo_radius_miles: string
  language: string
  timezone: string
  sender_name: string
  sender_email: string
  owner_name: string
  owner_whatsapp: string
}

const EMPTY: FormState = {
  tenant_id: '',
  company_name: '',
  geo_center: '',
  geo_radius_miles: '50',
  language: 'en',
  timezone: 'America/Chicago',
  sender_name: '',
  sender_email: '',
  owner_name: '',
  owner_whatsapp: '',
}

export default function NewTenantModal({ onClose, onCreated }: Props) {
  const [form, setForm] = useState<FormState>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const set = (field: keyof FormState) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) => setForm(prev => ({ ...prev, [field]: e.target.value }))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const resp = await fetch(`${API_BASE}/api/v1/tenants`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
        },
        body: JSON.stringify({
          ...form,
          geo_radius_miles: parseInt(form.geo_radius_miles, 10) || 50,
        }),
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        throw new Error(data.detail ?? `HTTP ${resp.status}`)
      }
      onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create tenant')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(2,13,36,0.85)', backdropFilter: 'blur(4px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-lg rounded-xl flex flex-col gap-0 overflow-hidden"
        style={{ border: '0.5px solid var(--border)', background: 'var(--surface)' }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: '0.5px solid var(--border)' }}
        >
          <h2 className="text-sm font-bold tracking-tight">New Tenant</h2>
          <button
            onClick={onClose}
            className="text-muted hover:text-white transition-colors text-lg leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-5">

          {/* Tenant ID + Company */}
          <Row>
            <Field label="Tenant ID" hint="tenant_001 format">
              <input
                required
                pattern="^tenant_\d{3,}$"
                placeholder="tenant_003"
                value={form.tenant_id}
                onChange={set('tenant_id')}
              />
            </Field>
            <Field label="Company name">
              <input
                required
                placeholder="Acme Corp"
                value={form.company_name}
                onChange={set('company_name')}
              />
            </Field>
          </Row>

          {/* Geo — the location where the scraper will search */}
          <Row>
            <Field label="Scraping location" hint="City + State where the agent searches for leads">
              <input
                required
                placeholder="Houston, TX"
                value={form.geo_center}
                onChange={set('geo_center')}
              />
            </Field>
            <Field label="Radius (miles)">
              <input
                type="number"
                min={1}
                max={500}
                value={form.geo_radius_miles}
                onChange={set('geo_radius_miles')}
              />
            </Field>
          </Row>

          {/* Language + Timezone */}
          <Row>
            <Field label="Language">
              <select value={form.language} onChange={set('language')}>
                <option value="en">English</option>
                <option value="es">Español</option>
                <option value="both">Both</option>
              </select>
            </Field>
            <Field label="Timezone">
              <select value={form.timezone} onChange={set('timezone')}>
                <option value="America/Chicago">America/Chicago</option>
                <option value="America/New_York">America/New_York</option>
                <option value="America/Denver">America/Denver</option>
                <option value="America/Los_Angeles">America/Los_Angeles</option>
                <option value="America/Mexico_City">America/Mexico_City</option>
              </select>
            </Field>
          </Row>

          <div style={{ borderTop: '0.5px solid var(--border)', margin: '0 -1.25rem', padding: '0 1.25rem' }} />

          {/* Sender */}
          <Row>
            <Field label="Sender name">
              <input
                required
                placeholder="Carlos Rodriguez"
                value={form.sender_name}
                onChange={set('sender_name')}
              />
            </Field>
            <Field label="Sender email">
              <input
                required
                type="email"
                placeholder="carlos@company.com"
                value={form.sender_email}
                onChange={set('sender_email')}
              />
            </Field>
          </Row>

          {/* Owner */}
          <Row>
            <Field label="Owner name">
              <input
                required
                placeholder="Carlos"
                value={form.owner_name}
                onChange={set('owner_name')}
              />
            </Field>
            <Field label="Owner WhatsApp">
              <input
                required
                placeholder="+15551234567"
                value={form.owner_whatsapp}
                onChange={set('owner_whatsapp')}
              />
            </Field>
          </Row>

          {error && (
            <p className="text-xs text-bizon-danger font-mono">{error}</p>
          )}

          {/* Actions */}
          <div
            className="flex justify-end gap-2 pt-1"
            style={{ borderTop: '0.5px solid var(--border)', marginTop: 4 }}
          >
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-muted hover:text-white transition-colors rounded-md"
              style={{ border: '0.5px solid var(--border)' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 text-sm font-medium rounded-md bg-bizon-blue text-white disabled:opacity-50 transition-opacity"
            >
              {submitting ? 'Creating…' : 'Create tenant'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-3">{children}</div>
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactElement
}) {
  const inputClass =
    'w-full px-3 py-2 rounded-md text-xs font-mono bg-transparent text-white placeholder:text-muted outline-none focus:ring-1 focus:ring-bizon-blue/60 transition-shadow'
  const styledChild = {
    ...children,
    props: { ...children.props, className: inputClass },
  }
  return (
    <div className="flex flex-col gap-1">
      <label className="text-2xs text-muted uppercase tracking-widest font-medium">
        {label}
        {hint && <span className="normal-case tracking-normal ml-1 text-muted/60">— {hint}</span>}
      </label>
      <div style={{ border: '0.5px solid var(--border)', borderRadius: 6 }}>
        {styledChild}
      </div>
    </div>
  )
}
