import clsx from 'clsx'
import type { LeadStatus } from '@/lib/types'

const STATUS_COLORS: Record<LeadStatus, string> = {
  new:          'bg-bizon-blue',
  contacted:    'bg-bizon-tan',
  responded:    'bg-bizon-success',
  meeting_set:  'bg-bizon-success',
  closed_won:   'bg-bizon-success',
  closed_lost:  'bg-neutral-500',
  no_response:  'bg-bizon-danger',
}

const STATUS_LABELS: Record<LeadStatus, string> = {
  new:          'New',
  contacted:    'Contacted',
  responded:    'Responded',
  meeting_set:  'Meeting set',
  closed_won:   'Closed won',
  closed_lost:  'Closed lost',
  no_response:  'No response',
}

interface StatusDotProps {
  status: LeadStatus
  showLabel?: boolean
  size?: 'sm' | 'md'
}

export default function StatusDot({ status, showLabel = false, size = 'md' }: StatusDotProps) {
  const dotSize = size === 'sm' ? 'w-1.5 h-1.5' : 'w-2 h-2'
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={clsx('rounded-full flex-shrink-0', dotSize, STATUS_COLORS[status])} />
      {showLabel && (
        <span className="text-muted text-xs font-mono">{STATUS_LABELS[status]}</span>
      )}
    </span>
  )
}
