'use client'

import { useState, useEffect, useRef } from 'react'

interface NominatimResult {
  place_id: number
  display_name: string
  address: {
    city?: string
    town?: string
    village?: string
    municipality?: string
    county?: string
    state?: string
    country?: string
    country_code?: string
  }
}

interface Suggestion {
  id: number
  label: string        // short label used as the value (e.g. "Houston, Texas, US")
  detail: string       // full display_name shown below the label
}

function buildLabel(item: NominatimResult): string {
  const a = item.address
  const parts: string[] = []

  const city = a.city ?? a.town ?? a.village ?? a.municipality ?? a.county ?? ''
  if (city)    parts.push(city)
  if (a.state) parts.push(a.state)
  if (a.country_code) parts.push(a.country_code.toUpperCase())

  return parts.length ? parts.join(', ') : item.display_name.split(',').slice(0, 2).join(',').trim()
}

export interface GeoAutocompleteProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string      // applied to the <input> element
  autoFocus?: boolean
}

export default function GeoAutocomplete({
  value,
  onChange,
  placeholder = 'Houston, TX',
  className = '',
  autoFocus = false,
}: GeoAutocompleteProps) {
  const [query, setQuery]           = useState(value)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [loading, setLoading]       = useState(false)
  const [open, setOpen]             = useState(false)
  const [activeIdx, setActiveIdx]   = useState(-1)

  const containerRef = useRef<HTMLDivElement>(null)
  const abortRef     = useRef<AbortController | null>(null)

  // Sync when parent changes value externally
  useEffect(() => { setQuery(value) }, [value])

  // Debounced Nominatim search
  useEffect(() => {
    if (query.trim().length < 2) {
      setSuggestions([])
      setOpen(false)
      return
    }

    const timer = setTimeout(async () => {
      abortRef.current?.abort()
      abortRef.current = new AbortController()
      setLoading(true)
      setActiveIdx(-1)
      try {
        const url =
          `https://nominatim.openstreetmap.org/search` +
          `?q=${encodeURIComponent(query)}&format=json&addressdetails=1&limit=7`
        const resp = await fetch(url, {
          signal: abortRef.current.signal,
          headers: { 'Accept-Language': 'en' },
        })
        const data: NominatimResult[] = await resp.json()
        const seen = new Set<string>()
        const items: Suggestion[] = []
        for (const item of data) {
          const label = buildLabel(item)
          if (!seen.has(label)) {
            seen.add(label)
            items.push({ id: item.place_id, label, detail: item.display_name })
          }
        }
        setSuggestions(items)
        setOpen(items.length > 0)
      } catch (err: any) {
        if (err.name !== 'AbortError') setSuggestions([])
      } finally {
        setLoading(false)
      }
    }, 350)

    return () => clearTimeout(timer)
  }, [query])

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const select = (s: Suggestion) => {
    setQuery(s.label)
    onChange(s.label)
    setOpen(false)
    setSuggestions([])
    setActiveIdx(-1)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault()
      select(suggestions[activeIdx])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <input
        autoFocus={autoFocus}
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholder}
        value={query}
        className={className}
        onChange={e => {
          setQuery(e.target.value)
          onChange(e.target.value)
        }}
        onFocus={() => suggestions.length > 0 && setOpen(true)}
        onKeyDown={handleKeyDown}
      />

      {/* Loading spinner inside input */}
      {loading && (
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-2xs text-muted font-mono animate-pulse pointer-events-none">
          …
        </span>
      )}

      {/* Dropdown */}
      {open && suggestions.length > 0 && (
        <ul
          className="absolute left-0 right-0 z-[200] mt-1 rounded-md overflow-hidden"
          style={{
            top: '100%',
            border: '0.5px solid var(--border)',
            background: '#0a1628',
            boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          }}
        >
          {suggestions.map((s, idx) => (
            <li key={s.id}>
              <button
                type="button"
                onMouseDown={e => { e.preventDefault(); select(s) }}
                className="w-full text-left px-3 py-2 flex flex-col gap-0.5 transition-colors"
                style={{
                  background: idx === activeIdx ? 'rgba(2,149,253,0.12)' : 'transparent',
                  borderBottom: idx < suggestions.length - 1 ? '0.5px solid var(--border)' : undefined,
                }}
                onMouseEnter={() => setActiveIdx(idx)}
              >
                <span className="text-xs font-mono text-white">{s.label}</span>
                <span className="text-2xs font-mono text-muted truncate">{s.detail}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
