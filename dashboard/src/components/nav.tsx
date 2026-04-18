import Link from 'next/link'
import { createClient } from '@/lib/supabase/server'
import { GateBadge } from './gate-badge'
import type { PendingCounts } from '@/lib/types'

async function getPendingCounts(): Promise<PendingCounts> {
  const supabase = await createClient()

  const [
    { count: gate1 },
    { count: gate2 },
    { count: gate3 },
    { count: gate4 },
    { count: gate5 },
    { count: gate6 },
  ] = await Promise.all([
    supabase.from('niches').select('*', { count: 'exact', head: true }).eq('gate1_state', 'awaiting_review'),
    supabase.from('topics').select('*', { count: 'exact', head: true }).eq('gate2_state', 'awaiting_review'),
    supabase.from('scripts').select('*', { count: 'exact', head: true }).eq('gate3_state', 'awaiting_review'),
    supabase.from('videos').select('*', { count: 'exact', head: true }).eq('gate4_state', 'awaiting_review'),
    supabase.from('videos').select('*', { count: 'exact', head: true }).eq('gate5_state', 'awaiting_review'),
    supabase.from('videos').select('*', { count: 'exact', head: true }).eq('gate6_state', 'awaiting_review'),
  ])

  return {
    gate1: gate1 ?? 0,
    gate2: gate2 ?? 0,
    gate3: gate3 ?? 0,
    gate4: gate4 ?? 0,
    gate5: gate5 ?? 0,
    gate6: gate6 ?? 0,
  }
}

const NAV_LINKS = [
  { href: '/', label: 'Home' },
  { href: '/niches', label: 'Niches', gateKey: 'gate1' as keyof PendingCounts },
  { href: '/pipeline', label: 'Pipeline' },
  { href: '/topics', label: 'Topic Queue', gateKey: 'gate2' as keyof PendingCounts },
  { href: '/scripts', label: 'Script Review', gateKey: 'gate3' as keyof PendingCounts },
  { href: '/media', label: 'Media Review', gateKey: null },
  { href: '/analytics', label: 'Analytics' },
  { href: '/settings', label: 'Settings' },
]

export async function Nav() {
  const counts = await getPendingCounts()
  const mediaTotal = counts.gate4 + counts.gate5 + counts.gate6

  return (
    <nav className="w-56 shrink-0 bg-gray-900 text-gray-200 flex flex-col h-screen sticky top-0">
      <div className="px-4 py-5 text-white font-bold text-lg border-b border-gray-700">
        YouTubeNiche
      </div>
      <ul className="flex flex-col gap-1 p-2 flex-1">
        {NAV_LINKS.map(({ href, label, gateKey }) => {
          const count =
            gateKey === null
              ? mediaTotal
              : gateKey
              ? counts[gateKey]
              : 0
          return (
            <li key={href}>
              <Link
                href={href}
                className="flex items-center px-3 py-2 rounded hover:bg-gray-700 text-sm"
              >
                {label}
                {count > 0 && <GateBadge count={count} />}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
