/**
 * Smoke tests for components/RAGManager.tsx
 *
 * Verifies the component renders, shows the drop zone and docs heading,
 * fetches documents on mount, and displays the empty state when no docs exist.
 * All network calls are mocked via global.fetch.
 */

import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'

// ── next/link → plain <a> ─────────────────────────────────────────────────────
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: any) =>
    React.createElement('a', { href, ...rest }, children),
}))

// ── fetch mock helpers ────────────────────────────────────────────────────────

function mockFetchOk(body: unknown) {
  return jest.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(body),
    } as Response),
  )
}

function mockFetchError(status = 500) {
  return jest.fn(() =>
    Promise.resolve({
      ok: false,
      status,
      json: () => Promise.resolve({}),
    } as Response),
  )
}

// ── Import under test ─────────────────────────────────────────────────────────

import RAGManager from '@/components/RAGManager'

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('RAGManager', () => {
  beforeEach(() => {
    global.fetch = mockFetchOk({ documents: [] })
  })

  afterEach(() => {
    jest.restoreAllMocks()
  })

  it('renders without crashing', () => {
    const { container } = render(<RAGManager tenantId="tenant_001" />)
    expect(container.firstChild).toBeTruthy()
  })

  it('renders the drop zone', () => {
    render(<RAGManager tenantId="tenant_001" />)
    expect(screen.getByTestId('drop-zone')).toBeInTheDocument()
  })

  it('renders the "Indexed documents" heading', () => {
    render(<RAGManager tenantId="tenant_001" />)
    expect(screen.getByTestId('docs-heading')).toBeInTheDocument()
    expect(screen.getByTestId('docs-heading')).toHaveTextContent(/indexed documents/i)
  })

  it('fetches documents on mount', async () => {
    render(<RAGManager tenantId="tenant_001" authToken="test-token" />)
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(1)
    })
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toMatch(
      /\/rag\/tenant_001\/documents/,
    )
  })

  it('shows empty state when no documents are returned', async () => {
    render(<RAGManager tenantId="tenant_001" />)
    await waitFor(() => {
      expect(screen.getByTestId('docs-empty')).toBeInTheDocument()
    })
  })

  it('shows documents in a table when the API returns docs', async () => {
    global.fetch = mockFetchOk({
      documents: [
        { filename: 'servicios.md', size_bytes: 1024, last_modified: '2026-07-10T00:00:00Z' },
        { filename: 'precios.md',   size_bytes: 512,  last_modified: '2026-07-11T00:00:00Z' },
      ],
    })
    render(<RAGManager tenantId="tenant_001" />)
    await waitFor(() => {
      expect(screen.getByTestId('docs-table')).toBeInTheDocument()
    })
    expect(screen.getByText('servicios.md')).toBeInTheDocument()
    expect(screen.getByText('precios.md')).toBeInTheDocument()
  })

  it('shows an error message when the fetch fails', async () => {
    global.fetch = mockFetchError(503)
    render(<RAGManager tenantId="tenant_001" />)
    await waitFor(() => {
      expect(screen.getByTestId('docs-error')).toBeInTheDocument()
    })
  })

  it('passes the Authorization header when authToken is provided', async () => {
    render(<RAGManager tenantId="tenant_001" authToken="my-secret-token" />)
    await waitFor(() => expect(global.fetch).toHaveBeenCalled())
    const [, options] = (global.fetch as jest.Mock).mock.calls[0]
    expect(options?.headers?.Authorization).toBe('Bearer my-secret-token')
  })
})
