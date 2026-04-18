import { createClient } from '@/lib/supabase/server'
import { StatusPill } from '@/components/status-pill'
import type { Niche } from '@/lib/types'

const GATE_LABELS: Record<number, string> = {
  1: 'Niche Activation',
  2: 'Topic Selection',
  3: 'Script',
  4: 'Voiceover',
  5: 'Thumbnail',
  6: 'Final Video',
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
    { data: topicCounts },
    { data: scriptCounts },
    { data: videoCounts },
  ] = await Promise.all([
    supabase.from('topics').select('niche_id, gate2_state').in('niche_id', nicheIds),
    supabase.from('scripts').select('niche_id, gate3_state').in('niche_id', nicheIds),
    supabase.from('videos').select('niche_id, gate4_state, gate5_state, gate6_state').in('niche_id', nicheIds),
  ])

  const countsByNiche = (nicheId: string) => ({
    gate2_pending: topicCounts?.filter((t) => t.niche_id === nicheId && t.gate2_state === 'awaiting_review').length ?? 0,
    gate3_pending: scriptCounts?.filter((s) => s.niche_id === nicheId && s.gate3_state === 'awaiting_review').length ?? 0,
    gate4_pending: videoCounts?.filter((v) => v.niche_id === nicheId && v.gate4_state === 'awaiting_review').length ?? 0,
    gate5_pending: videoCounts?.filter((v) => v.niche_id === nicheId && v.gate5_state === 'awaiting_review').length ?? 0,
    gate6_pending: videoCounts?.filter((v) => v.niche_id === nicheId && v.gate6_state === 'awaiting_review').length ?? 0,
  })

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Pipeline</h1>
      <div className="space-y-4">
        {(niches as Niche[]).map((niche) => {
          const counts = countsByNiche(niche.id)
          return (
            <div key={niche.id} className="bg-white border border-gray-200 rounded-lg p-5">
              <div className="flex items-center gap-3 mb-4">
                <StatusPill status={niche.status} />
                <span className="font-semibold">{niche.name}</span>
                <span className="text-xs text-gray-400">{niche.category}</span>
              </div>
              <div className="grid grid-cols-6 gap-2">
                {[2, 3, 4, 5, 6].map((gate) => {
                  const pending = counts[`gate${gate}_pending` as keyof typeof counts]
                  return (
                    <div
                      key={gate}
                      className={`rounded p-2 text-center text-xs border ${
                        pending > 0 ? 'border-orange-400 bg-orange-50' : 'border-gray-200 bg-gray-50'
                      }`}
                    >
                      <p className="font-medium text-gray-700">Gate {gate}</p>
                      <p className="text-gray-500">{GATE_LABELS[gate]}</p>
                      {pending > 0 && (
                        <p className="text-orange-600 font-bold mt-1">{pending} pending</p>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
