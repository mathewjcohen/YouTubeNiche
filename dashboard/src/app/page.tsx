import { createClient } from '@/lib/supabase/server'

async function getHomeStats() {
  const supabase = await createClient()

  const [
    { count: activeChannels },
    { count: pendingGate1 },
    { count: pendingGate2 },
    { count: pendingGate3 },
    { count: pendingGate5 },
    { count: pendingGate6 },
    { data: recentAnalytics },
  ] = await Promise.all([
    supabase.from('niches').select('*', { count: 'exact', head: true }).in('status', ['testing', 'promoted']),
    supabase.from('niches').select('*', { count: 'exact', head: true }).eq('gate1_state', 'awaiting_review'),
    supabase.from('topics').select('*', { count: 'exact', head: true }).eq('gate2_state', 'awaiting_review'),
    supabase.from('scripts').select('*', { count: 'exact', head: true }).eq('gate3_state', 'awaiting_review'),
    supabase.from('videos').select('*', { count: 'exact', head: true }).eq('gate5_state', 'awaiting_review'),
    supabase.from('videos').select('*', { count: 'exact', head: true }).eq('gate6_state', 'awaiting_review'),
    supabase.from('niche_analytics').select('views_7d').order('measured_at', { ascending: false }).limit(10),
  ])

  const totalPending = (pendingGate1 ?? 0) + (pendingGate2 ?? 0) + (pendingGate3 ?? 0) + (pendingGate5 ?? 0) + (pendingGate6 ?? 0)
  const weeklyViews = (recentAnalytics ?? []).reduce((sum, r) => sum + r.views_7d, 0)

  return { activeChannels: activeChannels ?? 0, totalPending, weeklyViews }
}

export default async function HomePage() {
  const stats = await getHomeStats()

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Network Overview</h1>
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Active Channels" value={stats.activeChannels} />
        <StatCard label="Pending Reviews" value={stats.totalPending} highlight={stats.totalPending > 0} />
        <StatCard label="Views (7 days)" value={stats.weeklyViews.toLocaleString()} />
      </div>
    </div>
  )
}

function StatCard({ label, value, highlight }: { label: string; value: string | number; highlight?: boolean }) {
  return (
    <div className={`rounded-lg border p-5 bg-white shadow-sm ${highlight ? 'border-orange-400' : 'border-gray-200'}`}>
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${highlight ? 'text-orange-500' : 'text-gray-900'}`}>{value}</p>
    </div>
  )
}
