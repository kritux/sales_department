'use client'

import Image from 'next/image'
import type { SystemState } from '@/lib/types'

// ─── Constants ────────────────────────────────────────────────────────────────

const W = 680
const H = 340
const CX = W / 2   // 340
const CY = H / 2   // 170
const RX = 175     // horizontal ellipse radius
const RY = 128     // vertical ellipse radius

const CENTER_IMAGE: Record<SystemState, string> = {
  scanning: '/assets/bizon/bizon_13_scanning_spiral_eyes.png',
  success:  '/assets/bizon/bizon_08_content_smile_teeth.png',
  standby:  '/assets/bizon/bizon_15_calm_relaxed.png',
  error:    '/assets/bizon/bizon_16_error_glitch_eyes.png',
}

const BLUE   = '#0295fd'
const TAN    = '#9e7a57'

// ─── Satellite layout ─────────────────────────────────────────────────────────
// 6 nodes at 60° intervals on an ellipse, starting from right (0°)

function ellipsePoint(angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180
  return {
    x: CX + RX * Math.cos(rad),
    y: CY + RY * Math.sin(rad),
  }
}

type NodeKind = 'agent' | 'tenant'

interface SatelliteConfig {
  id: string
  defaultLabel: string
  kind: NodeKind
  angle: number
}

const SATELLITE_CONFIGS: SatelliteConfig[] = [
  { id: 'scout',    defaultLabel: 'Scout',       kind: 'agent',  angle: -90 },  // top
  { id: 'email',    defaultLabel: 'Email Agent', kind: 'agent',  angle: -30 },  // upper-right
  { id: 'director', defaultLabel: 'Director',    kind: 'agent',  angle:  30 },  // lower-right
  { id: 't1',       defaultLabel: 'tenant_001',  kind: 'tenant', angle:  90 },  // bottom
  { id: 't2',       defaultLabel: 'tenant_002',  kind: 'tenant', angle: 150 },  // lower-left
  { id: 't3',       defaultLabel: 'tenant_003',  kind: 'tenant', angle: -150 }, // upper-left
]

const AGENT_IMG  = '/assets/bizon/bizon_14_excited_sparkle_eyes.png'
const TENANT_IMG = '/assets/bizon/bizon_01_default_smile.png'

// ─── Component ────────────────────────────────────────────────────────────────

export interface BizonNetworkHeroProps {
  state?: SystemState
  tenants?: Array<{ id: string; name: string }>
  className?: string
}

export default function BizonNetworkHero({
  state = 'standby',
  tenants,
  className,
}: BizonNetworkHeroProps) {
  const centerSrc = CENTER_IMAGE[state]

  const satellites = SATELLITE_CONFIGS.map((cfg, idx) => {
    const pos = ellipsePoint(cfg.angle)
    const tenantIndex = SATELLITE_CONFIGS.slice(0, idx).filter(c => c.kind === 'tenant').length
    const label =
      cfg.kind === 'tenant' && tenants?.[tenantIndex]
        ? tenants[tenantIndex].name
        : cfg.defaultLabel
    return { ...cfg, pos, label }
  })

  return (
    <div
      className={className}
      style={{
        position: 'relative',
        width: '100%',
        height: `${H}px`,
        background: '#050505',
        borderRadius: '12px',
        overflow: 'hidden',
      }}
    >
      {/* ── SVG connection lines ─────────────────────────────────────────── */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
        aria-hidden
      >
        {satellites.map((node, i) => (
          <line
            key={node.id}
            x1={CX}
            y1={CY}
            x2={node.pos.x}
            y2={node.pos.y}
            stroke={BLUE}
            strokeWidth="0.75"
            style={{
              animation: 'bizonPulseLine 2.4s ease-in-out infinite',
              animationDelay: `${i * 0.4}s`,
            }}
          />
        ))}
      </svg>

      {/* ── Radial glow behind center ────────────────────────────────────── */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          width: '200px',
          height: '200px',
          left: `${(CX / W) * 100}%`,
          top:  `${(CY / H) * 100}%`,
          transform: 'translate(-50%, -50%)',
          background: 'radial-gradient(circle, rgba(2,149,253,0.52) 0%, rgba(2,149,253,0.1) 45%, transparent 70%)',
          filter: 'blur(22px)',
          zIndex: 1,
          animation: 'bizonGlowPulse 3s ease-in-out infinite',
          borderRadius: '50%',
        }}
      />

      {/* ── Center node ───────────────────────────────────────────────────── */}
      <div
        style={{
          position: 'absolute',
          left: `${(CX / W) * 100}%`,
          top:  `${(CY / H) * 100}%`,
          transform: 'translate(-50%, -50%)',
          zIndex: 10,
        }}
      >
        <div
          style={{
            width: '96px',
            height: '96px',
            borderRadius: '14px',
            border: `2px solid ${BLUE}`,
            overflow: 'hidden',
            position: 'relative',
          }}
        >
          <Image
            src={centerSrc}
            alt="Bizon AI core"
            width={96}
            height={96}
            style={{ objectFit: 'cover', display: 'block' }}
            priority
          />
        </div>
      </div>

      {/* ── Satellite nodes ───────────────────────────────────────────────── */}
      {satellites.map((node, i) => (
        <div
          key={node.id}
          style={{
            position: 'absolute',
            left: `${(node.pos.x / W) * 100}%`,
            top:  `${(node.pos.y / H) * 100}%`,
            transform: 'translate(-50%, -50%)',
            zIndex: 10,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '5px',
            animation: 'bizonNodeAppear 0.5s ease-out both',
            animationDelay: `${i * 0.12}s`,
          }}
        >
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '8px',
              border: `1px solid ${node.kind === 'tenant' ? TAN : BLUE}`,
              overflow: 'hidden',
            }}
          >
            <Image
              src={node.kind === 'agent' ? AGENT_IMG : TENANT_IMG}
              alt={node.label}
              width={40}
              height={40}
              style={{ objectFit: 'cover', display: 'block' }}
            />
          </div>
          <span
            style={{
              fontSize: '10px',
              fontFamily: 'var(--font-mono), JetBrains Mono, monospace',
              color: node.kind === 'tenant' ? TAN : '#6b85ab',
              whiteSpace: 'nowrap',
              maxWidth: '72px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              textAlign: 'center',
              lineHeight: 1.2,
            }}
          >
            {node.label}
          </span>
        </div>
      ))}

      {/* ── State badge ───────────────────────────────────────────────────── */}
      <div
        style={{
          position: 'absolute',
          top: '12px',
          right: '14px',
          display: 'flex',
          alignItems: 'center',
          gap: '5px',
          fontSize: '10px',
          fontFamily: 'var(--font-mono), JetBrains Mono, monospace',
          color: STATE_COLOR[state],
          opacity: 0.85,
        }}
      >
        <span
          style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: STATE_COLOR[state],
            display: 'inline-block',
          }}
        />
        {STATE_LABEL[state]}
      </div>
    </div>
  )
}

const STATE_COLOR: Record<SystemState, string> = {
  scanning: '#0295fd',
  success:  '#2ecc8f',
  standby:  '#9e7a57',
  error:    '#ff4d4d',
}

const STATE_LABEL: Record<SystemState, string> = {
  scanning: 'Scanning',
  success:  'Success',
  standby:  'Standby',
  error:    'Error',
}
