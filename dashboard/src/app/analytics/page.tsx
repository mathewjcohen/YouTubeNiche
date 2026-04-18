import { createClient } from '@/lib/supabase/server'
import { StatusPill } from '@/components/status-pill'
import type { Niche, NicheAnalytics } from '@/lib/types'

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
  const { data: analytics } = await supabase
    .from('niche_analytics')
    .select('*')
    .in('niche_id', nicheIds)
    .order('polled_at', { ascending: false })

  const latestByNiche: Record<string, NicheAnalytics> = {}
  for (const row of analytics ?? []) {
    if (!latestByNiche[row.niche_id]) latestByNiche[row.niche_id] = row as NicheAnalytics
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Analytics</h1>
      <div className="grid grid-cols-1 gap-4">
        {(niches as Niche[]).map((niche) => {
          const latest = latestByNiche[niche.id]
          return (
            <div key={niche.id} className="bg-gray-800 border border-gray-700 rounded-lg p-5">
              <div className="flex items-center gap-3 mb-4">
                <StatusPill status={niche.status} />
                <span className="font-semibold text-gray-100">{niche.name}</span>
                <span className="text-xs text-gray-500">{niche.category}</span>
                {latest?.early_promotion_flagged && (
                  <span className="ml-auto bg-yellow-900/40 text-yellow-300 text-xs px-2 py-0.5 rounded-full font-medium">
                    Early Promotion Flagged
                  </span>
                )}
              </div>
              {!latest ? (
                <p className="text-sm text-gray-500">No analytics yet.</p>
              ) : (
                <div className="grid grid-cols-4 gap-4">
                  <Metric label="Views (total)" value={latest.views_total.toLocaleString()} />
                  <Metric
                    label="CTR"
                    value={`${(latest.ctr * 100).toFixed(1)}%`}
                    highlight={latest.ctr >= 0.03}
                  />
                  <Metric
                    label="Avg Watch Time"
                    value={`${(latest.avg_watch_time_pct * 100).toFixed(0)}%`}
                    highlight={latest.avg_watch_time_pct >= 0.35}
                  />
                  <Metric label="Subs (total)" value={latest.subs_total.toLocaleString()} />
                </div>
              )}
            </div>
          )
        })}
      </div>
      <p className="text-xs text-gray-600 mt-4">
        Promotion threshold: CTR ≥ 3% AND avg watch time ≥ 35% AND 50+ views (60-day review)
      </p>
    </div>
  )
}

function Metric({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="text-center">
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`text-xl font-bold mt-1 ${highlight ? 'text-green-400' : 'text-gray-100'}`}>{value}</p>
    </div>
  )
}
