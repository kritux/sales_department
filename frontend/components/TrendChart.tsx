'use client'

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
} from 'recharts'
import type { TrendPoint } from '@/lib/tenant-data'

const TICK_STYLE = {
  fontSize: 10,
  fill: '#666',
  fontFamily: 'var(--font-mono), JetBrains Mono, monospace',
}

const TOOLTIP_STYLE = {
  background: '#0d0d0d',
  border: '0.5px solid rgba(255,255,255,0.08)',
  borderRadius: '6px',
  fontSize: '11px',
  fontFamily: 'var(--font-mono), JetBrains Mono, monospace',
  color: '#fff',
  padding: '8px 12px',
}

interface TrendChartProps {
  data: TrendPoint[]
  height?: number
}

export default function TrendChart({ data, height = 200 }: TrendChartProps) {
  const intervalVal = data.length > 14 ? Math.floor(data.length / 6) : 0

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 8, left: -28, bottom: 0 }}>
        <XAxis
          dataKey="date"
          tick={TICK_STYLE}
          tickLine={false}
          axisLine={false}
          interval={intervalVal}
        />
        <YAxis
          tick={TICK_STYLE}
          tickLine={false}
          axisLine={false}
          width={36}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          cursor={{ stroke: 'rgba(255,255,255,0.06)', strokeWidth: 1 }}
          itemStyle={{ color: '#ccc', padding: '1px 0' }}
          labelStyle={{ color: '#fff', marginBottom: 4, fontWeight: 600 }}
        />
        <Line
          type="monotone"
          dataKey="leads"
          name="Leads"
          stroke="#0295fd"
          strokeWidth={1.5}
          dot={false}
          activeDot={{ r: 3, fill: '#0295fd', strokeWidth: 0 }}
        />
        <Line
          type="monotone"
          dataKey="emails"
          name="Emails"
          stroke="#9e7a57"
          strokeWidth={1.5}
          dot={false}
          activeDot={{ r: 3, fill: '#9e7a57', strokeWidth: 0 }}
        />
        <Line
          type="monotone"
          dataKey="responses"
          name="Responses"
          stroke="#2ecc8f"
          strokeWidth={1.5}
          dot={false}
          activeDot={{ r: 3, fill: '#2ecc8f', strokeWidth: 0 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
