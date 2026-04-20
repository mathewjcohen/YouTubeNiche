'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { GateBadge } from './gate-badge'
import type { PendingCounts } from '@/lib/types'

const NAV_LINKS = [
  { href: '/', label: 'Home' },
  { href: '/niches', label: 'Niches', gateKey: 'gate1' as keyof PendingCounts },
{ href: '/topics', label: 'Topic Queue', gateKey: 'gate2' as keyof PendingCounts },
  { href: '/scripts', label: 'Script Review', gateKey: 'gate3' as keyof PendingCounts },
  { href: '/media', label: 'Media Review', gateKey: null },
  { href: '/analytics', label: 'Analytics' },
  { href: '/settings', label: 'Settings' },
]

export function NavLinks({ counts, mediaTotal }: { counts: PendingCounts; mediaTotal: number }) {
  const pathname = usePathname()

  return (
    <ul className="flex flex-col gap-1 p-2 flex-1">
      {NAV_LINKS.map(({ href, label, gateKey }) => {
        const count = gateKey === null ? mediaTotal : gateKey ? counts[gateKey] : 0
        const active = href === '/' ? pathname === '/' : pathname.startsWith(href)
        return (
          <li key={href}>
            <Link
              href={href}
              className={`flex items-center px-3 py-2 rounded text-sm transition-colors ${
                active
                  ? 'bg-gray-700 text-white font-medium'
                  : 'text-gray-300 hover:bg-gray-700 hover:text-white'
              }`}
            >
              {label}
              {count > 0 && <GateBadge count={count} />}
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
