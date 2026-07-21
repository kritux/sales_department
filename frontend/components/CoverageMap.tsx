'use client'

import { useEffect, useRef, useState } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface MapLead {
  id: string
  company_name: string
  lat: number
  lng: number
}

export interface CoverageMapProps {
  centerLat: number
  centerLng: number
  geoCenter: string
  radiusMiles: number
  leads: MapLead[]
  className?: string
}

// ─── Constants ────────────────────────────────────────────────────────────────

const MILES_TO_METERS = 1609.344

const TILES = {
  dark:  'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  light: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
}
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'

const BLUE = '#0295fd'
const TAN  = '#9e7a57'

// ─── Haversine distance (km) ──────────────────────────────────────────────────

function haversineKm(
  lat1: number, lng1: number,
  lat2: number, lng2: number,
): number {
  const R = 6371
  const dLat = ((lat2 - lat1) * Math.PI) / 180
  const dLng = ((lng2 - lng1) * Math.PI) / 180
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
    Math.cos((lat2 * Math.PI) / 180) *
    Math.sin(dLng / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function isInsideRadius(
  lead: MapLead,
  centerLat: number,
  centerLng: number,
  radiusMiles: number,
): boolean {
  const distKm = haversineKm(centerLat, centerLng, lead.lat, lead.lng)
  return distKm <= radiusMiles * 1.60934
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function CoverageMap({
  centerLat,
  centerLng,
  geoCenter,
  radiusMiles,
  leads,
  className,
}: CoverageMapProps) {
  const mapRef = useRef<HTMLDivElement>(null)
  const [isDark, setIsDark] = useState(false)
  const [leadsInside, setLeadsInside] = useState(0)
  // Keep track of leaflet map instance to avoid re-initialising
  const leafletRef = useRef<any>(null)

  useEffect(() => {
    setIsDark(document.documentElement.classList.contains('dark'))
  }, [])

  useEffect(() => {
    const inside = leads.filter(l =>
      isInsideRadius(l, centerLat, centerLng, radiusMiles)
    ).length
    setLeadsInside(inside)
  }, [leads, centerLat, centerLng, radiusMiles])

  useEffect(() => {
    if (!mapRef.current) return

    // Leaflet must be imported client-side (needs window)
    import('leaflet').then(({ default: L }) => {
      // Leaflet's default icon path breaks in Next.js — fix it
      // @ts-expect-error _getIconUrl is not in types
      delete L.Icon.Default.prototype._getIconUrl
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
        iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
        shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
      })

      if (leafletRef.current) {
        leafletRef.current.remove()
        leafletRef.current = null
      }

      const tileUrl = isDark ? TILES.dark : TILES.light
      const map = L.map(mapRef.current!, {
        center: [centerLat, centerLng],
        zoom: 11,
        zoomControl: true,
        attributionControl: true,
      })

      L.tileLayer(tileUrl, { attribution: TILE_ATTRIBUTION, maxZoom: 18 }).addTo(map)

      // Coverage circle
      const radiusMeters = radiusMiles * MILES_TO_METERS
      L.circle([centerLat, centerLng], {
        radius: radiusMeters,
        color: BLUE,
        fillColor: BLUE,
        fillOpacity: 0.07,
        weight: 1.5,
        opacity: 0.6,
      }).addTo(map)

      // Center pin
      const centerIcon = L.divIcon({
        className: '',
        html: `<div style="
          width:14px; height:14px; border-radius:50%;
          background:${BLUE}; border:2.5px solid #fff;
          box-shadow:0 0 0 2px ${BLUE};
        "></div>`,
        iconSize: [14, 14],
        iconAnchor: [7, 7],
      })
      L.marker([centerLat, centerLng], { icon: centerIcon })
        .addTo(map)
        .bindPopup(`<b>${geoCenter}</b><br>Center of coverage area`)

      // Lead markers
      leads.forEach(lead => {
        const inside = isInsideRadius(lead, centerLat, centerLng, radiusMiles)
        const color  = inside ? BLUE : TAN
        const icon   = L.divIcon({
          className: '',
          html: `<div style="
            width:10px; height:10px; border-radius:50%;
            background:${color}; border:1.5px solid #fff;
            box-shadow:0 0 0 1px ${color};
          "></div>`,
          iconSize: [10, 10],
          iconAnchor: [5, 5],
        })
        L.marker([lead.lat, lead.lng], { icon })
          .addTo(map)
          .bindPopup(`<b>${lead.company_name}</b>`)
      })

      leafletRef.current = map
    })

    return () => {
      if (leafletRef.current) {
        leafletRef.current.remove()
        leafletRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDark, centerLat, centerLng, radiusMiles])

  return (
    <div className={className}>
      {/* Leaflet CSS — loaded once client-side */}
      {/* eslint-disable-next-line @next/next/no-css-tags */}
      <link
        rel="stylesheet"
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        crossOrigin=""
      />

      {/* Map canvas */}
      <div
        ref={mapRef}
        style={{
          height: '280px',
          width: '100%',
          borderRadius: '8px',
          border: '0.5px solid var(--border)',
          overflow: 'hidden',
          background: isDark ? '#111' : '#f0f0f0',
        }}
      />

      {/* Legend + stats bar */}
      <div
        className="flex items-center justify-between flex-wrap gap-2 mt-2"
        style={{ fontSize: '11px', fontFamily: 'var(--font-mono), JetBrains Mono, monospace' }}
      >
        <span style={{ color: 'var(--text-muted)' }}>
          Centro:{' '}
          <span style={{ color: 'var(--text)' }}>{geoCenter}</span>
          {' · '}Radio:{' '}
          <span style={{ color: 'var(--text)' }}>{radiusMiles} millas</span>
          {' · '}
          <span style={{ color: BLUE }}>{leadsInside} leads dentro del radio hoy</span>
        </span>

        <span className="flex items-center gap-3" style={{ color: 'var(--text-muted)' }}>
          <span className="flex items-center gap-1">
            <span
              style={{
                width: '8px', height: '8px', borderRadius: '50%',
                background: BLUE, display: 'inline-block',
              }}
            />
            dentro
          </span>
          <span className="flex items-center gap-1">
            <span
              style={{
                width: '8px', height: '8px', borderRadius: '50%',
                background: TAN, display: 'inline-block',
              }}
            />
            fuera
          </span>
        </span>
      </div>
    </div>
  )
}
