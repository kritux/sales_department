'use client'

import { useState } from 'react'
import clsx from 'clsx'
import type { LeadCriteria } from '@/lib/types'

const INDUSTRY_OPTIONS = [
  'General Contractor', 'Plumber', 'Electrician', 'HVAC', 'Roofer',
  'Painter', 'Landscaper', 'Flooring', 'Concrete', 'Welder',
  'Handyman', 'Pest Control', 'Cleaning', 'Other',
]

interface LeadProfileBuilderProps {
  initial?: Partial<LeadCriteria>
  onChange?: (criteria: LeadCriteria) => void
}

const DEFAULT_CRITERIA: LeadCriteria = {
  min_rating: 3.5,
  min_reviews: 10,
  max_reviews: null,
  has_website: null,
  company_size: 'any',
  industries: [],
  exclude_keywords: [],
}

export default function LeadProfileBuilder({ initial, onChange }: LeadProfileBuilderProps) {
  const [criteria, setCriteria] = useState<LeadCriteria>({ ...DEFAULT_CRITERIA, ...initial })
  const [kwInput, setKwInput] = useState('')

  const update = (patch: Partial<LeadCriteria>) => {
    const next = { ...criteria, ...patch }
    setCriteria(next)
    onChange?.(next)
  }

  const toggleIndustry = (ind: string) => {
    const next = criteria.industries.includes(ind)
      ? criteria.industries.filter(i => i !== ind)
      : [...criteria.industries, ind]
    update({ industries: next })
  }

  const addKeyword = () => {
    const kw = kwInput.trim()
    if (!kw || criteria.exclude_keywords.includes(kw)) return
    update({ exclude_keywords: [...criteria.exclude_keywords, kw] })
    setKwInput('')
  }

  const removeKeyword = (kw: string) => {
    update({ exclude_keywords: criteria.exclude_keywords.filter(k => k !== kw) })
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Rating + Reviews */}
      <div className="grid grid-cols-2 gap-4">
        <Field label="Min rating">
          <input
            type="number"
            min={1}
            max={5}
            step={0.5}
            value={criteria.min_rating}
            onChange={e => update({ min_rating: parseFloat(e.target.value) })}
            className="input-flat"
          />
        </Field>
        <Field label="Min reviews">
          <input
            type="number"
            min={0}
            value={criteria.min_reviews}
            onChange={e => update({ min_reviews: parseInt(e.target.value) })}
            className="input-flat"
          />
        </Field>
      </div>

      {/* Website filter */}
      <Field label="Has website">
        <div className="flex gap-2">
          {([null, true, false] as const).map(v => (
            <button
              key={String(v)}
              onClick={() => update({ has_website: v })}
              className={clsx(
                'px-3 py-1.5 text-xs font-mono rounded transition-colors',
                criteria.has_website === v
                  ? 'bg-bizon-blue text-white'
                  : 'bg-surface text-muted hover:text-white',
              )}
              style={{ border: '0.5px solid var(--border)' }}
            >
              {v === null ? 'Any' : v ? 'Yes' : 'No'}
            </button>
          ))}
        </div>
      </Field>

      {/* Company size */}
      <Field label="Company size">
        <div className="flex gap-2 flex-wrap">
          {(['any', 'small', 'medium', 'large'] as const).map(s => (
            <button
              key={s}
              onClick={() => update({ company_size: s })}
              className={clsx(
                'px-3 py-1.5 text-xs font-mono rounded capitalize transition-colors',
                criteria.company_size === s
                  ? 'bg-bizon-blue text-white'
                  : 'bg-surface text-muted hover:text-white',
              )}
              style={{ border: '0.5px solid var(--border)' }}
            >
              {s}
            </button>
          ))}
        </div>
      </Field>

      {/* Industries */}
      <Field label="Target industries">
        <div className="flex flex-wrap gap-1.5">
          {INDUSTRY_OPTIONS.map(ind => (
            <button
              key={ind}
              onClick={() => toggleIndustry(ind)}
              className={clsx(
                'px-2.5 py-1 text-2xs font-mono rounded transition-colors',
                criteria.industries.includes(ind)
                  ? 'bg-bizon-tan text-white'
                  : 'bg-surface text-muted hover:text-white',
              )}
              style={{ border: '0.5px solid var(--border)' }}
            >
              {ind}
            </button>
          ))}
        </div>
      </Field>

      {/* Exclude keywords */}
      <Field label="Exclude keywords">
        <div className="flex gap-2 mb-2">
          <input
            type="text"
            value={kwInput}
            onChange={e => setKwInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addKeyword()}
            placeholder="e.g. franchise"
            className="input-flat flex-1"
          />
          <button
            onClick={addKeyword}
            className="px-3 py-1.5 text-xs font-mono rounded bg-surface text-muted hover:text-white transition-colors"
            style={{ border: '0.5px solid var(--border)' }}
          >
            Add
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {criteria.exclude_keywords.map(kw => (
            <span
              key={kw}
              className="inline-flex items-center gap-1 px-2 py-0.5 text-2xs font-mono rounded bg-surface text-muted"
              style={{ border: '0.5px solid var(--border)' }}
            >
              {kw}
              <button
                onClick={() => removeKeyword(kw)}
                className="text-bizon-danger hover:opacity-80 ml-0.5 leading-none"
                aria-label={`Remove ${kw}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      </Field>

      {/* Summary */}
      <div
        className="rounded-md p-3 bg-surface font-mono text-2xs text-muted"
        style={{ border: '0.5px solid var(--border)' }}
      >
        <pre className="whitespace-pre-wrap break-words">
          {JSON.stringify(criteria, null, 2)}
        </pre>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-mono text-muted uppercase tracking-widest">{label}</label>
      {children}
    </div>
  )
}
