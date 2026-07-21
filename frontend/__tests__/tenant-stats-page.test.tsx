/**
 * Smoke test for app/tenants/[id]/page.tsx
 *
 * Verifies the page renders the Coverage area section and key UI elements
 * without throwing. Leaflet and Recharts are stubbed to avoid window deps.
 */

import React from 'react'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'

// ── Stubs for modules that need the browser environment ──────────────────────

// next/dynamic — return a component that renders null (covers TrendChart + CoverageMap)
jest.mock('next/dynamic', () => (factory: () => any, _opts?: any) => {
  return function DynamicStub() { return null }
})

// next/image → plain <img>
jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: any) => React.createElement('img', props),
}))

// next/link → plain <a>
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: any) =>
    React.createElement('a', { href, ...rest }, children),
}))

// clsx is a real package — no stub needed

// ── Import under test ────────────────────────────────────────────────────────

import TenantStatsPage from '@/app/tenants/[id]/page'

// ── Tests ────────────────────────────────────────────────────────────────────

describe('TenantStatsPage', () => {
  it('renders without crashing for a known tenant', () => {
    const { container } = render(<TenantStatsPage params={{ id: 'tenant_001' }} />)
    expect(container.firstChild).toBeTruthy()
  })

  it('renders without crashing for an unknown tenant (fallback meta)', () => {
    const { container } = render(<TenantStatsPage params={{ id: 'unknown_tenant' }} />)
    expect(container.firstChild).toBeTruthy()
  })

  it('shows the tenant name in the header', () => {
    render(<TenantStatsPage params={{ id: 'tenant_001' }} />)
    expect(screen.getByText('Growth Bizon')).toBeInTheDocument()
  })

  it('shows the coverage area section heading', () => {
    render(<TenantStatsPage params={{ id: 'tenant_001' }} />)
    expect(screen.getByText(/coverage area/i)).toBeInTheDocument()
  })

  it('shows the funnel section heading', () => {
    render(<TenantStatsPage params={{ id: 'tenant_001' }} />)
    expect(screen.getByText(/funnel/i)).toBeInTheDocument()
  })

  it('shows time range buttons', () => {
    render(<TenantStatsPage params={{ id: 'tenant_001' }} />)
    expect(screen.getByText('Today')).toBeInTheDocument()
    expect(screen.getByText('7 days')).toBeInTheDocument()
    expect(screen.getByText('30 days')).toBeInTheDocument()
  })

  it('shows recent leads section', () => {
    render(<TenantStatsPage params={{ id: 'tenant_001' }} />)
    expect(screen.getByText(/recent leads/i)).toBeInTheDocument()
  })

  it('shows cost breakdown section', () => {
    render(<TenantStatsPage params={{ id: 'tenant_001' }} />)
    expect(screen.getByText(/cost breakdown/i)).toBeInTheDocument()
  })
})
