import { createClient } from '@/lib/supabase/server'
import { StatusPill } from '@/components/status-pill'
import type { Niche, NicheAnalytics, VideoAnalytics } from '@/lib/types'

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(0)}%`
}

function fmtDur(sec: number | null | undefined): string {
  if (sec == null || sec === 0) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function fmtNum(v: number | null | undefined): string {
  if (v == null) return '—'
  return v.toLocaleString()
}

export default async function AnalyticsPage() {
  const supabase = await createClient()

  const { data: niches } = await supabase
    .from('niches')
    .select('id, name, category, status')
    .in('status', ['testing', 'promoted'])
    .order('status')

  if (!niches?.length) {
    return (
      <div>
        <h1 className="text-2xl font-bold mb-4">Analytics</h1>
        <p className="text-gray-500">No active niches yet.</p>
      </div>
    )
  }

  const nicheIds = niches.map((n) => n.id)

  const [{ data: analyticsRows }, { data: videoRows }] = await Promise.all([
    supabase
      .from('niche_analytics')
      .select('*')
      .in('niche_id', nicheIds)
      .order('polled_at', { ascending: false }),
    supabase
      .from('video_analytics')
      .select('*')
      .in('niche_id', nicheIds)
      .order('polled_at', { ascending: false }),
  ])

  const latestByNiche: Record<string, NicheAnalytics> = {}
  for (const row of analyticsRows ?? []) {
    if (!latestByNiche[row.niche_id]) latestByNiche[row.niche_id] = row as NicheAnalytics
  }

  // Latest snapshot per video (first occurrence = most recent due to order)
  const latestByVideo: Record<string, VideoAnalytics> = {}
  for (const row of videoRows ?? []) {
    if (!latestByVideo[row.youtube_video_id]) latestByVideo[row.youtube_video_id] = row as VideoAnalytics
  }

  const videosByNiche: Record<string, VideoAnalytics[]> = {}
  for (const v of Object.values(latestByVideo)) {
    if (!videosByNiche[v.niche_id]) videosByNiche[v.niche_id] = []
    videosByNiche[v.niche_id].push(v)
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Analytics</h1>
      <div className="grid grid-cols-1 gap-6">
        {(niches as Niche[]).map((niche) => {
          const a = latestByNiche[niche.id]
          const videos = videosByNiche[niche.id] ?? []
          const longs = videos.filter((v) => v.video_type === 'long')
          const shorts = videos.filter((v) => v.video_type === 'short')

          return (
            <div key={niche.id} className="bg-gray-800 border border-gray-700 rounded-lg p-5">
              {/* Header */}
              <div className="flex items-center gap-3 mb-5">
                <StatusPill status={niche.status} />
                <span className="font-semibold text-gray-100">{niche.name}</span>
                <span className="text-xs text-gray-500">{niche.category}</span>
                {a?.early_promotion_flagged && (
                  <span className="ml-auto bg-yellow-900/40 text-yellow-300 text-xs px-2 py-0.5 rounded-full font-medium">
                    Early Promotion Flagged
                  </span>
                )}
              </div>

              {!a ? (
                <p className="text-sm text-gray-500">No analytics yet.</p>
              ) : (
                <div className="space-y-5">
                  {/* Top-level metrics */}
                  <div className="grid grid-cols-4 gap-3">
                    <Metric label="Views (7d)" value={fmtNum(a.views_total)} />
                    <Metric label="Impressions" value={fmtNum(a.impressions)} />
                    <Metric label="Subscribers" value={`+${fmtNum(a.subscribers_gained)}`} />
                    <Metric label="Likes" value={fmtNum(a.likes)} />
                    <Metric
                      label="Watch Time"
                      value={fmtPct(a.avg_watch_time_pct)}
                      highlight={(a.avg_watch_time_pct ?? 0) >= 0.35}
                    />
                    <Metric label="Avg Duration" value={fmtDur(a.avg_view_duration_sec)} />
                    <Metric label="Est. Minutes Watched" value={fmtNum(a.estimated_minutes_watched)} />
                    <Metric label="Videos / Shorts" value={`${a.videos_published} / ${a.shorts_published}`} />
                  </div>

                  {/* Long-form vs Shorts split */}
                  {(a.long_views > 0 || a.short_views > 0) && (
                    <div className="grid grid-cols-2 gap-3">
                      <SplitCard
                        label="Long-form"
                        views={a.long_views}
                        watchPct={a.long_avg_watch_pct}
                        duration={a.long_avg_view_duration_sec}
                        threshold={0.35}
                      />
                      <SplitCard
                        label="Shorts"
                        views={a.short_views}
                        watchPct={a.short_avg_watch_pct}
                        duration={a.short_avg_view_duration_sec}
                        threshold={0.5}
                      />
                    </div>
                  )}

                  {/* Per-video table */}
                  {videos.length > 0 && (
                    <VideoTable longs={longs} shorts={shorts} />
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
      <p className="text-xs text-gray-600 mt-4">
        Promotion threshold: avg watch time ≥ 35% AND 50+ views (60-day review) · Data window: last 7 days
      </p>
    </div>
  )
}

function Metric({
  label,
  value,
  highlight,
}: {
  label: string
  value: string
  highlight?: boolean
}) {
  return (
    <div className="bg-gray-900/50 rounded-lg p-3 text-center">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-lg font-bold ${highlight ? 'text-green-400' : 'text-gray-100'}`}>{value}</p>
    </div>
  )
}

function SplitCard({
  label,
  views,
  watchPct,
  duration,
  threshold,
}: {
  label: string
  views: number
  watchPct: number | null
  duration: number | null
  threshold: number
}) {
  const good = (watchPct ?? 0) >= threshold
  return (
    <div className="bg-gray-900/50 rounded-lg p-3">
      <p className="text-xs font-medium text-gray-400 mb-2">{label}</p>
      <div className="grid grid-cols-3 gap-2">
        <div className="text-center">
          <p className="text-xs text-gray-600">Views</p>
          <p className="text-sm font-semibold text-gray-200">{fmtNum(views)}</p>
        </div>
        <div className="text-center">
          <p className="text-xs text-gray-600">Watch %</p>
          <p className={`text-sm font-semibold ${good ? 'text-green-400' : 'text-gray-200'}`}>
            {fmtPct(watchPct)}
          </p>
        </div>
        <div className="text-center">
          <p className="text-xs text-gray-600">Avg Duration</p>
          <p className="text-sm font-semibold text-gray-200">{fmtDur(duration)}</p>
        </div>
      </div>
    </div>
  )
}

function VideoTable({ longs, shorts }: { longs: VideoAnalytics[]; shorts: VideoAnalytics[] }) {
  const allVideos = [
    ...longs.map((v) => ({ ...v, label: 'Long' })),
    ...shorts.map((v) => ({ ...v, label: 'Short' })),
  ].sort((a, b) => b.views - a.views)

  return (
    <div>
      <p className="text-xs font-medium text-gray-400 mb-2">Per-video (latest snapshot)</p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-700">
              <th className="text-left pb-2 font-medium">Video ID</th>
              <th className="text-left pb-2 font-medium">Type</th>
              <th className="text-right pb-2 font-medium">Views</th>
              <th className="text-right pb-2 font-medium">Watch %</th>
              <th className="text-right pb-2 font-medium">Avg Duration</th>
              <th className="text-right pb-2 font-medium">Est. Min</th>
              <th className="text-right pb-2 font-medium">Likes</th>
            </tr>
          </thead>
          <tbody>
            {allVideos.map((v) => (
              <tr key={v.youtube_video_id} className="border-b border-gray-700/50 hover:bg-gray-700/20">
                <td className="py-1.5 font-mono text-gray-400">{v.youtube_video_id}</td>
                <td className="py-1.5">
                  <span
                    className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                      v.label === 'Long'
                        ? 'bg-blue-900/40 text-blue-300'
                        : 'bg-purple-900/40 text-purple-300'
                    }`}
                  >
                    {v.label}
                  </span>
                </td>
                <td className="py-1.5 text-right text-gray-200">{fmtNum(v.views)}</td>
                <td className={`py-1.5 text-right font-medium ${
                  v.label === 'Long'
                    ? (v.avg_view_pct ?? 0) >= 0.35 ? 'text-green-400' : 'text-gray-200'
                    : (v.avg_view_pct ?? 0) >= 0.5 ? 'text-green-400' : 'text-gray-200'
                }`}>
                  {fmtPct(v.avg_view_pct)}
                </td>
                <td className="py-1.5 text-right text-gray-200">{fmtDur(v.avg_view_duration_sec)}</td>
                <td className="py-1.5 text-right text-gray-200">{fmtNum(v.estimated_minutes_watched ?? null)}</td>
                <td className="py-1.5 text-right text-gray-200">{fmtNum(v.likes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
