import { createClient } from '@/lib/supabase/server'
import { NavLinks } from './nav-links'
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
    supabase.from('videos').select('*', { count: 'exact', head: true }).eq('gate5_state', 'awaiting_review').not('thumbnail_path', 'is', null),
    supabase.from('videos').select('*', { count: 'exact', head: true }).eq('gate6_state', 'awaiting_review').eq('gate4_state', 'approved').eq('gate5_state', 'approved'),
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

export async function Nav() {
  const counts = await getPendingCounts()
  const mediaTotal = counts.gate4 + counts.gate5 + counts.gate6

  return (
    <nav className="w-56 shrink-0 bg-gray-900 text-gray-200 flex flex-col h-screen sticky top-0">
      <div className="px-4 py-5 text-white font-bold text-lg border-b border-gray-700">
        YouTubeNiche
      </div>
      <NavLinks counts={counts} mediaTotal={mediaTotal} />
    </nav>
  )
}
