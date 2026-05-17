import type { Insight } from '@/lib/types'

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(0)}%`
}

function fmtNum(v: number | null | undefined): string {
  if (v == null) return '—'
  return v.toLocaleString()
}

function youtubeUrl(id: string, type: string): string {
  return type === 'short'
    ? `https://www.youtube.com/shorts/${id}`
    : `https://www.youtube.com/watch?v=${id}`
}

function BettermentTable({
  videos,
  dim,
}: {
  videos: Array<{ youtube_video_id: string; title: string; type: string; views: number; watch_pct: number }>
  dim?: boolean
}) {
  if (videos.length === 0) return null
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-gray-600 border-b border-gray-700">
          <th className="pb-1 font-medium">Title</th>
          <th className="pb-1 font-medium text-right w-16">Views</th>
          <th className="pb-1 font-medium text-right w-16">Watch %</th>
        </tr>
      </thead>
      <tbody>
        {videos.map((v) => (
          <tr key={v.youtube_video_id} className={`border-b border-gray-800 last:border-0 ${dim ? 'opacity-50' : ''}`}>
            <td className="py-1.5 pr-3">
              <a
                href={youtubeUrl(v.youtube_video_id, v.type)}
                target="_blank"
                rel="noreferrer"
                className="text-blue-400 hover:text-blue-300 hover:underline truncate max-w-[320px] inline-block cursor-pointer"
                title={v.title}
              >
                {v.title.length > 55 ? v.title.slice(0, 52) + '…' : v.title}
              </a>
              <span className={`ml-2 text-xs px-1 rounded ${v.type === 'short' ? 'bg-purple-900/40 text-purple-400' : 'bg-blue-900/40 text-blue-400'}`}>
                {v.type}
              </span>
            </td>
            <td className="py-1.5 text-right text-gray-300">{v.views}</td>
            <td className="py-1.5 text-right text-gray-300">{fmtPct(v.watch_pct)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function InsightsWidget({ insight }: { insight: Insight | null }) {
  if (!insight) {
    return (
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-5">
        <h2 className="font-semibold text-gray-100 mb-2">Performance Insights</h2>
        <p className="text-sm text-gray-500">No insights yet — insights are generated weekly once videos have analytics data.</p>
      </div>
    )
  }

  const s = insight.stats_json
  const generatedDate = new Date(insight.generated_at).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  })

  const bullets = insight.summary_text
    .split('\n')
    .map((l) => l.replace(/^[-•*]\s*/, '').trim())
    .filter(Boolean)

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-5 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-gray-100">Performance Insights</h2>
        <span className="text-xs text-gray-600">{generatedDate} · last {insight.period_days}d</span>
      </div>

      {/* LLM summary */}
      <ul className="space-y-2">
        {bullets.map((b, i) => (
          <li key={i} className="flex gap-2 text-sm text-gray-300 leading-snug">
            <span className="text-blue-400 mt-0.5 shrink-0">·</span>
            <span>{b}</span>
          </li>
        ))}
      </ul>

      {/* Stats strip */}
      <div className="grid grid-cols-2 gap-3 pt-2 border-t border-gray-700 sm:grid-cols-4">
        <MiniStat label="Videos analyzed" value={fmtNum(s.total_videos)} />
        <MiniStat label="Total views" value={fmtNum(s.total_views)} />
        <MiniStat label="Avg watch %" value={fmtPct(s.overall_avg_watch_pct)} />
        {s.retention.avg_50pct_dropoff != null && (
          <MiniStat
            label="Avg 50% drop-off"
            value={fmtPct(s.retention.avg_50pct_dropoff)}
            hint="Point in video where half the audience has left"
          />
        )}
      </div>

      {/* By niche row */}
      {s.by_niche.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 mb-2">By niche (avg watch %)</p>
          <div className="flex flex-wrap gap-2">
            {s.by_niche.map((n) => (
              <div key={n.niche} className="bg-gray-900/60 rounded px-3 py-1.5 text-xs">
                <span className="text-gray-400">{n.niche}</span>
                <span className="ml-2 font-semibold text-gray-200">{fmtPct(n.avg_watch_pct)}</span>
                <span className="ml-1 text-gray-600">({n.video_count}v)</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Best script length */}
      {s.by_script_length.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 mb-2">Script length vs watch % (ranked)</p>
          <div className="flex flex-wrap gap-2">
            {s.by_script_length.map((b, i) => (
              <div key={b.script_length} className={`rounded px-3 py-1.5 text-xs ${i === 0 ? 'bg-green-900/30 border border-green-700/40' : 'bg-gray-900/60'}`}>
                <span className="text-gray-400">{b.script_length}</span>
                <span className="ml-2 font-semibold text-gray-200">{fmtPct(b.avg_watch_pct)}</span>
                <span className="ml-1 text-gray-600">({b.count}v)</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Betterment section */}
      {(s.top_5_videos?.length > 0 || insight.betterment_text) && (
        <div className="pt-4 border-t border-gray-700 space-y-4">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Betterment</p>

          {s.top_5_videos?.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">Top performers</p>
              <BettermentTable videos={s.top_5_videos} />
            </div>
          )}

          {s.bottom_5_videos?.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">Bottom performers</p>
              <BettermentTable videos={s.bottom_5_videos} dim />
            </div>
          )}

          {insight.betterment_text && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">What to act on</p>
              <ul className="space-y-2">
                {insight.betterment_text
                  .split('\n')
                  .map((l) => l.replace(/^[-•*]\s*/, '').trim())
                  .filter(Boolean)
                  .map((b, i) => (
                    <li key={i} className="flex gap-2 text-sm text-gray-300 leading-snug">
                      <span className="text-green-400 mt-0.5 shrink-0">·</span>
                      <span>{b}</span>
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function MiniStat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="relative group">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-lg font-bold text-gray-100">{value}</p>
      {hint && (
        <div className="pointer-events-none hidden group-hover:block absolute bottom-full mb-1 left-0 z-50 w-48 bg-gray-900 border border-gray-600 rounded p-2 text-xs text-gray-400 shadow-xl">
          {hint}
        </div>
      )}
    </div>
  )
}
