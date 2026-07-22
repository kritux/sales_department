'use client'

import { useState, useEffect, useCallback } from 'react'
import TenantCard from '@/components/TenantCard'
import NewTenantModal from '@/components/NewTenantModal'
import type { TenantConfig } from '@/lib/types'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? ''

export default function TenantsPage() {
  const [tenants, setTenants] = useState<TenantConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showModal, setShowModal] = useState(false)

  const fetchTenants = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const resp = await fetch(`${API_BASE}/api/v1/tenants`, {
        headers: API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {},
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setTenants(await resp.json())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tenants')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchTenants() }, [fetchTenants])

  const active = tenants.filter(t => t.active)

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold tracking-tight">Tenants</h1>
          <p className="text-xs text-muted font-mono mt-0.5">
            {loading ? '…' : `${active.length} active · ${tenants.length} total`}
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="px-3 py-1.5 text-xs font-mono rounded-md text-white bg-bizon-blue hover:opacity-90 transition-opacity"
        >
          + New tenant
        </button>
      </div>

      {error && (
        <p className="text-xs text-bizon-danger font-mono" data-testid="tenants-error">
          {error}
        </p>
      )}

      {loading && (
        <p className="text-xs text-muted font-mono animate-pulse">Loading tenants…</p>
      )}

      {!loading && !error && tenants.length === 0 && (
        <p className="text-xs text-muted font-mono">
          No tenants yet. Click <span className="text-white">+ New tenant</span> to create one.
        </p>
      )}

      {tenants.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {tenants.map(t => (
            <TenantCard
              key={t.tenant_id}
              tenant={t}
              leadsToday={0}
              emailsToday={0}
            />
          ))}
        </div>
      )}

      {showModal && (
        <NewTenantModal
          onClose={() => setShowModal(false)}
          onCreated={() => { setShowModal(false); fetchTenants() }}
        />
      )}
    </div>
  )
}
