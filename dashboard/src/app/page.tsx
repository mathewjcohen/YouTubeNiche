import { createClient } from '@/lib/supabase/server'
import { StatusPill } from '@/components/status-pill'
import { Collapsible } from '@/components/collapsible'
import { FunnelChart } from '@/components/charts/funnel-chart'
import { ViewsChart } from '@/components/charts/views-chart'
import type { Niche } from '@/lib/types'

const GATE_LABELS: Record<number, string> = {
  2: 'Topic Selection',
  3: 'Script',
  4: 'Voiceover',
  5: 'Thumbnail',
  6: 'Final Video',
}

type StateCounts = { approved: number; awaiting: number; pending: number; total: number }

function tally(rows: { state: string }[]): StateCounts {
  const approved = rows.filter((r) => r.state === 'approved').length
  const awaiting = rows.filter((r) => r.state === 'awaiting_review').length
  const pending  = rows.filter((r) => r.state === 'pending').length
  return { approved, awaiting, pending, total: rows.length }
}

async function getHomeData() {
  const supabase = await createClient()

  const [
    { data: linkedNiches },
    { count: pendingGate1 },
    { count: pendingGate2 },
    { count: pendingGate3 },
    { count: pendingGate4 },
    { count: pendingGate5 },
    { count: pendingGate6 },
    { data: recentAnalytics },
    { data: niches },
    { data: topics },
    { data: scripts },
    { data: videos },
  ] = await Promise.all([
    supabase.from('niches').select('name, youtube_account_id, youtube_accounts(channel_name)').eq('channel_state', 'linked').not('youtube_account_id', 'is', null),
    supabase.from('niches').select('*', { count: 'exact', head: true }).eq('gate1_state', 'awaiting_review'),
    supabase.from('topics').select('*', { count: 'exact', head: true }).eq('gate2_state', 'awaiting_review'),
    supabase.from('scripts').select('*', { count: 'exact', head: true }).eq('gate3_state', 'awaiting_review'),
    supabase.from('videos').select('*', { count: 'exact', head: true }).eq('gate4_state', 'awaiting_review'),
    supabase.from('videos').select('*', { count: 'exact', head: true }).eq('gate5_state', 'awaiting_review').not('thumbnail_path', 'is', null),
    supabase.from('videos').select('*', { count: 'exact', head: true }).eq('gate6_state', 'awaiting_review').eq('gate4_state', 'approved').eq('gate5_state', 'approved'),
    supabase.from('niche_analytics').select('polled_at, views_total, videos_published, shorts_published, niche_id').order('polled_at', { ascending: false }).limit(60),
    supabase.from('niches').select('id, name, category, status').in('status', ['testing', 'promoted']).order('status'),
    supabase.from('topics').select('niche_id, gate2_state'),
    supabase.from('scripts').select('niche_id, gate3_state'),
    supabase.from('videos').select('niche_id, gate4_state, gate5_state, gate6_state, thumbnail_path'),
  ])

  // Active channels — distinct YouTube accounts, grouped with their niches
  const channelNicheMap = new Map<string, string[]>()
  for (const n of linkedNiches ?? []) {
    const acc = n.youtube_accounts
    const chName = (Array.isArray(acc) ? acc[0] : acc)?.channel_name ?? 'Unknown'
    if (!channelNicheMap.has(chName)) channelNicheMap.set(chName, [])
    channelNicheMap.get(chName)!.push(n.name)
  }
  const activeChannels = channelNicheMap.size
  const channelGroups = Array.from(channelNicheMap.entries()).map(([channel, nicheNames]) => ({ channel, nicheNames }))

  const totalPending = (pendingGate1 ?? 0) + (pendingGate2 ?? 0) + (pendingGate3 ?? 0)
    + (pendingGate4 ?? 0) + (pendingGate5 ?? 0) + (pendingGate6 ?? 0)

  const pendingBreakdown = [
    { gate: 'G1 Niches',    count: pendingGate1 ?? 0 },
    { gate: 'G2 Topics',    count: pendingGate2 ?? 0 },
    { gate: 'G3 Scripts',   count: pendingGate3 ?? 0 },
    { gate: 'G4 Voiceover', count: pendingGate4 ?? 0 },
    { gate: 'G5 Thumbnail', count: pendingGate5 ?? 0 },
    { gate: 'G6 Video',     count: pendingGate6 ?? 0 },
  ]

  // Most recent snapshot per niche — sum for top-level stats
  type AnalyticsRow = NonNullable<typeof recentAnalytics>[0]
  const latestByNiche = new Map<string, AnalyticsRow>()
  for (const row of recentAnalytics ?? []) {
    if (!latestByNiche.has(row.niche_id)) latestByNiche.set(row.niche_id, row)
  }
  const weeklyViews = Array.from(latestByNiche.values()).reduce((s, r) => s + (r.views_total ?? 0), 0)
  const publishedVideos = Array.from(latestByNiche.values()).reduce((s, r) => s + (r.videos_published ?? 0), 0)
  const publishedShorts = Array.from(latestByNiche.values()).reduce((s, r) => s + (r.shorts_published ?? 0), 0)

  const nicheNameMap = new Map((niches ?? []).map((n) => [n.id, n.name]))
  const analyticsBreakdown = Array.from(latestByNiche.entries()).map(([nicheId, row]) => ({
    name: nicheNameMap.get(nicheId) ?? nicheId.slice(0, 8),
    videos: row.videos_published ?? 0,
    shorts: row.shorts_published ?? 0,
    views: row.views_total ?? 0,
  }))

  // Build funnel data from actual counts
  const totalTopics = (topics ?? []).length
  const totalScripts = (scripts ?? []).length
  const totalVideos = (videos ?? []).length
  const funnelData = [
    { stage: 'Topics', count: totalTopics },
    { stage: 'Scripts', count: totalScripts },
    { stage: 'Videos', count: totalVideos },
    { stage: 'Published', count: publishedVideos + publishedShorts },
  ]

  // Gate queue breakdown
  const gateQueue = pendingBreakdown.filter((g) => g.count > 0)

  // Views over time: group by date, sum across niches
  const viewsByDate = new Map<string, number>()
  for (const row of recentAnalytics ?? []) {
    const date = row.polled_at.slice(0, 10)
    viewsByDate.set(date, (viewsByDate.get(date) ?? 0) + row.views_total)
  }
  const viewsTimeline = Array.from(viewsByDate.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-14)
    .map(([date, views]) => ({ date, views }))

  const countsForNiche = (nicheId: string) => {
    const nicheVideos = (videos ?? []).filter((v) => v.niche_id === nicheId)
    return {
      2: tally((topics ?? []).filter((t) => t.niche_id === nicheId).map((t) => ({ state: t.gate2_state }))),
      3: tally((scripts ?? []).filter((s) => s.niche_id === nicheId).map((s) => ({ state: s.gate3_state }))),
      4: tally(nicheVideos.map((v) => ({ state: v.gate4_state }))),
      5: tally(nicheVideos.filter((v) => v.thumbnail_path != null).map((v) => ({ state: v.gate5_state }))),
      6: tally(nicheVideos.filter((v) => v.gate4_state === 'approved' && v.gate5_state === 'approved').map((v) => ({ state: v.gate6_state }))),
    }
  }

  return {
    activeChannels,
    channelGroups,
    totalPending,
    pendingBreakdown,
    weeklyViews,
    publishedVideos,
    publishedShorts,
    analyticsBreakdown,
    funnelData,
    gateQueue,
    viewsTimeline,
    niches: (niches ?? []) as Niche[],
    countsForNiche,
  }
}

export default async function HomePage() {
  const data = await getHomeData()

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold mb-6">Network Overview</h1>

        {/* Stat cards */}
        <div className="grid grid-cols-5 gap-4">
          <StatCard
            label="Active Channels"
            value={data.activeChannels}
            tooltip={
              <div className="space-y-3">
                {data.channelGroups.map(({ channel, nicheNames }) => (
                  <div key={channel}>
                    <p className="font-semibold text-gray-100 mb-1">{channel}</p>
                    <ul className="space-y-0.5">
                      {nicheNames.map((n) => (
                        <li key={n} className="text-gray-400 pl-2 before:content-['·'] before:mr-1.5 before:text-gray-600">{n}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            }
          />
          <StatCard
            label="Pending Reviews"
            value={data.totalPending}
            highlight={data.totalPending > 0}
            tooltip={
              <div className="space-y-1">
                <p className="font-semibold text-gray-100 mb-2">By gate</p>
                {data.pendingBreakdown.map(({ gate, count }) => (
                  <div key={gate} className="flex justify-between gap-4">
                    <span className="text-gray-400">{gate}</span>
                    <span className={count > 0 ? 'text-orange-400 font-medium' : 'text-gray-600'}>{count}</span>
                  </div>
                ))}
              </div>
            }
          />
          <StatCard
            label="Published Videos"
            value={data.publishedVideos}
            tooltip={
              <div className="space-y-1">
                <p className="font-semibold text-gray-100 mb-2">By niche</p>
                {data.analyticsBreakdown.map(({ name, videos }) => (
                  <div key={name} className="flex justify-between gap-4">
                    <span className="text-gray-400 truncate max-w-[140px]">{name}</span>
                    <span className="text-gray-200 font-medium shrink-0">{videos}</span>
                  </div>
                ))}
              </div>
            }
          />
          <StatCard
            label="Published Shorts"
            value={data.publishedShorts}
            tooltip={
              <div className="space-y-1">
                <p className="font-semibold text-gray-100 mb-2">By niche</p>
                {data.analyticsBreakdown.map(({ name, shorts }) => (
                  <div key={name} className="flex justify-between gap-4">
                    <span className="text-gray-400 truncate max-w-[140px]">{name}</span>
                    <span className="text-gray-200 font-medium shrink-0">{shorts}</span>
                  </div>
                ))}
              </div>
            }
          />
          <StatCard
            label="7-Day Views"
            value={data.weeklyViews.toLocaleString()}
            tooltip={
              <div className="space-y-1">
                <p className="font-semibold text-gray-100 mb-2">By niche</p>
                {data.analyticsBreakdown.map(({ name, views }) => (
                  <div key={name} className="flex justify-between gap-4">
                    <span className="text-gray-400 truncate max-w-[140px]">{name}</span>
                    <span className="text-gray-200 font-medium shrink-0">{views.toLocaleString()}</span>
                  </div>
                ))}
                <p className="pt-2 mt-1 border-t border-gray-700 text-gray-500">Rolling 7-day window from YouTube Analytics</p>
              </div>
            }
          />
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-2 gap-6">
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-5">
          <h2 className="font-semibold text-gray-100 mb-4">Production Funnel</h2>
          <FunnelChart data={data.funnelData} />
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-5">
          <h2 className="font-semibold text-gray-100 mb-4">Views Over Time</h2>
          <ViewsChart data={data.viewsTimeline} />
        </div>
      </div>

      {/* Gate review queue */}
      {data.gateQueue.length > 0 && (
        <div className="bg-gray-800 border border-orange-800/50 rounded-lg p-5">
          <h2 className="font-semibold text-gray-100 mb-4">Review Queue</h2>
          <div className="flex gap-3 flex-wrap">
            {data.gateQueue.map((g) => (
              <div key={g.gate} className="bg-orange-900/30 border border-orange-700/50 rounded px-3 py-2 text-center min-w-[90px]">
                <p className="text-xs text-orange-300 font-medium">{g.gate}</p>
                <p className="text-2xl font-bold text-orange-400">{g.count}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pipeline section */}
      {data.niches.length > 0 && (
        <div>
          <h2 className="font-semibold text-gray-100 mb-3">Pipeline by Niche</h2>
          <div className="space-y-3">
            {data.niches.map((niche) => {
              const counts = data.countsForNiche(niche.id)
              const hasAwaiting = Object.values(counts).some((c) => c.awaiting > 0)
              return (
                <div key={niche.id} className={`bg-gray-800 border rounded-lg ${hasAwaiting ? 'border-orange-700/60' : 'border-gray-700'}`}>
                  <Collapsible
                    defaultOpen={hasAwaiting}
                    className="p-5"
                    title={
                      <div className="flex items-center gap-3">
                        <StatusPill status={niche.status} />
                        <span className="font-semibold text-gray-100">{niche.name}</span>
                        <span className="text-xs text-gray-500">{niche.category}</span>
                        {hasAwaiting && (
                          <span className="text-xs bg-orange-900/50 text-orange-400 border border-orange-700/50 px-1.5 py-0.5 rounded ml-1">
                            needs review
                          </span>
                        )}
                      </div>
                    }
                  >
                    <div className="grid grid-cols-5 gap-2 mt-4">
                      {([2, 3, 4, 5, 6] as const).map((gate) => (
                        <GateCell key={gate} gate={gate} label={GATE_LABELS[gate]} counts={counts[gate]} />
                      ))}
                    </div>
                  </Collapsible>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  highlight,
  tooltip,
}: {
  label: string
  value: string | number
  highlight?: boolean
  tooltip?: React.ReactNode
}) {
  return (
    <div className={`relative group rounded-lg border p-5 bg-gray-800 ${highlight ? 'border-orange-500' : 'border-gray-700'}`}>
      <p className="text-sm text-gray-400">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${highlight ? 'text-orange-400' : 'text-gray-100'}`}>{value}</p>
      {tooltip && (
        <div className="pointer-events-none hidden group-hover:block absolute left-0 top-full mt-2 z-50 w-56 bg-gray-900 border border-gray-600 rounded-lg p-3 text-xs text-gray-300 shadow-2xl">
          {tooltip}
        </div>
      )}
    </div>
  )
}

function GateCell({ gate, label, counts }: { gate: number; label: string; counts: StateCounts }) {
  const hasAwaiting = counts.awaiting > 0
  const hasApproved = counts.approved > 0
  const isEmpty = counts.total === 0

  const borderColor = hasAwaiting
    ? 'border-orange-600/60'
    : hasApproved
    ? 'border-green-700/60'
    : 'border-gray-700'

  const bgColor = hasAwaiting
    ? 'bg-orange-900/20'
    : hasApproved
    ? 'bg-green-900/20'
    : 'bg-gray-800/50'

  return (
    <div className={`rounded p-3 text-center text-xs border ${borderColor} ${bgColor}`}>
      <p className="font-semibold text-gray-300">Gate {gate}</p>
      <p className="text-gray-500 mb-2">{label}</p>
      {isEmpty ? (
        <p className="text-gray-600">—</p>
      ) : (
        <div className="space-y-1">
          {counts.awaiting > 0 && <p className="text-orange-400 font-bold">{counts.awaiting} review</p>}
          {counts.approved > 0 && <p className="text-green-400 font-medium">{counts.approved} approved</p>}
          {counts.pending > 0 && <p className="text-gray-500">{counts.pending} pending</p>}
        </div>
      )}
    </div>
  )
}
