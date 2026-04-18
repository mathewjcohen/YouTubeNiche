import { createClient } from '@/lib/supabase/server'
import { StatusPill } from '@/components/status-pill'
import { activateNiche, dismissNiche, archiveNiche, submitManualNiche } from '@/app/actions/niches'
import type { Niche, NicheStatus } from '@/lib/types'

const CATEGORIES = [
  'Legal / rights', 'Insurance', 'Tax / accounting', 'Personal finance',
  'Real estate', 'Career / salary', 'AI / tech tools', 'Health / medical',
]

const STATUS_ORDER: NicheStatus[] = ['candidate', 'testing', 'promoted', 'archived']

export default async function NichesPage() {
  const supabase = await createClient()
  const { data: niches } = await supabase
    .from('niches')
    .select('*')
    .order('score', { ascending: false })

  const grouped = STATUS_ORDER.reduce<Record<NicheStatus, Niche[]>>(
    (acc, s) => ({ ...acc, [s]: [] }),
    {} as Record<NicheStatus, Niche[]>
  )
  for (const n of niches ?? []) grouped[n.status as NicheStatus].push(n as Niche)

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Niches</h1>
      </div>

      <section className="bg-gray-800 border border-gray-700 rounded-lg p-5">
        <h2 className="font-semibold mb-3 text-gray-100">Score a Niche On Demand</h2>
        <form action={submitManualNiche} className="flex gap-3 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Niche idea</label>
            <input
              name="niche_name"
              required
              placeholder="e.g. landlord tenant rights"
              className="border border-gray-600 bg-gray-700 text-gray-100 placeholder:text-gray-500 rounded px-3 py-2 text-sm w-64"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Category</label>
            <select name="category" className="border border-gray-600 bg-gray-700 text-gray-100 rounded px-3 py-2 text-sm">
              {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <button
            type="submit"
            className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-blue-500"
          >
            Score Now
          </button>
        </form>
        <p className="text-xs text-gray-600 mt-2">
          Triggers GitHub Actions. Result appears below in ~2 min.
        </p>
      </section>

      {STATUS_ORDER.map((status) => (
        <section key={status}>
          <h2 className="font-semibold text-gray-400 mb-3 capitalize">
            {status} ({grouped[status].length})
          </h2>
          {grouped[status].length === 0 ? (
            <p className="text-sm text-gray-600">None</p>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {grouped[status].map((n) => (
                <NicheRow key={n.id} niche={n} />
              ))}
            </div>
          )}
        </section>
      ))}
    </div>
  )
}

function NicheRow({ niche }: { niche: Niche }) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 flex items-center gap-4">
      <StatusPill status={niche.status} />
      <div className="flex-1">
        <p className="font-medium text-gray-100">{niche.name}</p>
        <p className="text-xs text-gray-500">{niche.category}{niche.niche_source === 'manual' ? ' · [manual]' : ''}</p>
      </div>
      {niche.score != null && (
        <span className="text-sm text-gray-400">Score: {niche.score.toFixed(2)}</span>
      )}
      <div className="flex gap-2">
        {niche.gate1_state === 'awaiting_review' && (
          <>
            <form action={activateNiche.bind(null, niche.id)}>
              <button className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700">
                Activate
              </button>
            </form>
            <form action={dismissNiche.bind(null, niche.id)}>
              <button className="bg-gray-700 text-gray-300 text-xs px-3 py-1.5 rounded hover:bg-gray-600">
                Dismiss
              </button>
            </form>
          </>
        )}
        {niche.status === 'testing' && (
          <form action={archiveNiche.bind(null, niche.id)}>
            <button className="text-red-400 text-xs px-3 py-1.5 rounded hover:bg-red-900/30">
              Archive
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
