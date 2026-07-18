'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import clsx from 'clsx'
import BizonAvatar from './BizonAvatar'

const NAV = [
  { href: '/',          label: 'Command Center', icon: '⬡' },
  { href: '/tenants',   label: 'Tenants',        icon: '◈' },
  { href: '/settings',  label: 'Settings',       icon: '◎' },
]

interface SidebarProps {
  onThemeToggle?: () => void
  isDark?: boolean
}

export default function Sidebar({ onThemeToggle, isDark }: SidebarProps) {
  const pathname = usePathname()

  return (
    <aside
      className="flex flex-col h-full w-[200px] flex-shrink-0"
      style={{ borderRight: '0.5px solid var(--border)' }}
    >
      {/* Logo */}
      <div
        className="flex items-center gap-2.5 px-4 py-5"
        style={{ borderBottom: '0.5px solid var(--border)' }}
      >
        <BizonAvatar expression="default_smile" size={28} rounded="sm" priority />
        <div>
          <p className="text-xs font-bold tracking-widest uppercase" style={{ color: '#0295fd' }}>
            BIZON
          </p>
          <p className="text-2xs text-muted font-mono leading-none">Command Center</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 flex flex-col gap-0.5">
        {NAV.map(item => {
          const active =
            item.href === '/'
              ? pathname === '/'
              : pathname.startsWith(item.href)
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors duration-100',
                active
                  ? 'text-bizon-blue font-medium bg-bizon-blue/8'
                  : 'text-muted hover:text-white',
              )}
            >
              <span className="text-base leading-none w-4 text-center opacity-70">{item.icon}</span>
              {item.label}
            </Link>
          )
        })}
      </nav>

      {/* Theme toggle */}
      <div
        className="px-4 py-4"
        style={{ borderTop: '0.5px solid var(--border)' }}
      >
        <button
          onClick={onThemeToggle}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-xs text-muted hover:text-white transition-colors font-mono"
          style={{ border: '0.5px solid var(--border)' }}
        >
          <span className="text-sm">{isDark ? '☀' : '◑'}</span>
          {isDark ? 'Light mode' : 'Dark mode'}
        </button>
      </div>
    </aside>
  )
}
