import { createClient } from '@/lib/supabase/server'
import { StatusPill } from '@/components/status-pill'
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
          {counts.awaiting > 0 && (
            <p className="text-orange-400 font-bold">{counts.awaiting} review</p>
          )}
          {counts.approved > 0 && (
            <p className="text-green-400 font-medium">{counts.approved} approved</p>
          )}
          {counts.pending > 0 && (
            <p className="text-gray-500">{counts.pending} pending</p>
          )}
        </div>
      )}
    </div>
  )
}

export default async function PipelinePage() {
  const supabase = await createClient()

  const { data: niches } = await supabase
    .from('niches')
    .select('id, name, category, status')
    .in('status', ['testing', 'promoted'])
    .order('status')

  if (!niches?.length) {
    return (
      <div>
        <h1 className="text-2xl font-bold mb-4">Pipeline</h1>
        <p className="text-gray-500">No active niches.</p>
      </div>
    )
  }

  const nicheIds = niches.map((n) => n.id)

  const [
    { data: topics },
    { data: scripts },
    { data: videos },
  ] = await Promise.all([
    supabase.from('topics').select('niche_id, gate2_state').in('niche_id', nicheIds),
    supabase.from('scripts').select('niche_id, gate3_state').in('niche_id', nicheIds),
    supabase.from('videos').select('niche_id, gate4_state, gate5_state, gate6_state').in('niche_id', nicheIds),
  ])

  const countsForNiche = (nicheId: string) => ({
    2: tally((topics ?? []).filter((t) => t.niche_id === nicheId).map((t) => ({ state: t.gate2_state }))),
    3: tally((scripts ?? []).filter((s) => s.niche_id === nicheId).map((s) => ({ state: s.gate3_state }))),
    4: tally((videos ?? []).filter((v) => v.niche_id === nicheId).map((v) => ({ state: v.gate4_state }))),
    5: tally((videos ?? []).filter((v) => v.niche_id === nicheId).map((v) => ({ state: v.gate5_state }))),
    6: tally((videos ?? []).filter((v) => v.niche_id === nicheId).map((v) => ({ state: v.gate6_state }))),
  })

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Pipeline</h1>
      <div className="space-y-4">
        {(niches as Niche[]).map((niche) => {
          const counts = countsForNiche(niche.id)
          return (
            <div key={niche.id} className="bg-gray-800 border border-gray-700 rounded-lg p-5">
              <div className="flex items-center gap-3 mb-4">
                <StatusPill status={niche.status} />
                <span className="font-semibold text-gray-100">{niche.name}</span>
                <span className="text-xs text-gray-500">{niche.category}</span>
              </div>
              <div className="grid grid-cols-5 gap-2">
                {([2, 3, 4, 5, 6] as const).map((gate) => (
                  <GateCell
                    key={gate}
                    gate={gate}
                    label={GATE_LABELS[gate]}
                    counts={counts[gate]}
                  />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
