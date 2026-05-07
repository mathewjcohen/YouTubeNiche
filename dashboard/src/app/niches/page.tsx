import { createClient } from '@/lib/supabase/server'
import { StatusPill } from '@/components/status-pill'
import { ScoreTooltip } from '@/components/score-tooltip'
import { Form, SubmitButton } from '@/components/form'
import { activateNiche, dismissNiche, archiveNiche, promoteNiche, submitManualNiche } from '@/app/actions/niches'
import { NicheScoreChart } from '@/components/niche-score-chart'
import type { Niche, NicheStatus, NicheScoreDetails, ScoreHistoryRow } from '@/lib/types'

const CATEGORIES = [
  'Legal / rights', 'Insurance', 'Tax / accounting', 'Personal finance',
  'Real estate', 'Career / salary', 'AI / tech tools', 'Health / medical',
  'Home improvement', 'Parenting', 'Personal development', 'Relationships',
  'Travel', 'Food & cooking', 'Fitness', 'Beauty & skincare',
  'Small business', 'Side hustles', 'Crypto / Web3', 'Sustainability',
]

const STATUS_ORDER: NicheStatus[] = ['candidate', 'testing', 'promoted', 'archived']

export default async function NichesPage() {
  const supabase = await createClient()
  const [{ data: niches }, { data: historyRows }] = await Promise.all([
    supabase
      .from('niches')
      .select('*, youtube_accounts(channel_name, channel_id)')
      .order('score', { ascending: false }),
    supabase
      .from('niche_score_history')
      .select('niche_name, final_score, recorded_at')
      .gte('recorded_at', new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString())
      .order('recorded_at', { ascending: true }),
  ])

  const grouped = STATUS_ORDER.reduce<Record<NicheStatus, Niche[]>>(
    (acc, s) => ({ ...acc, [s]: [] }),
    {} as Record<NicheStatus, Niche[]>
  )
  for (const n of niches ?? []) grouped[n.status as NicheStatus].push(n as Niche)

  const history = (historyRows ?? []) as ScoreHistoryRow[]
  const nicheNames = Array.from(new Set(history.map((r) => r.niche_name)))

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Niches</h1>
      </div>

      <section className="bg-gray-800 border border-gray-700 rounded-lg p-5">
        <h2 className="font-semibold mb-3 text-gray-100">Score a Niche On Demand</h2>
        <Form action={submitManualNiche} successMessage="Queued — result appears in ~2 min" className="flex gap-3 items-end">
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
            <input
              name="category"
              list="category-suggestions"
              required
              placeholder="e.g. Legal / rights"
              className="border border-gray-600 bg-gray-700 text-gray-100 placeholder:text-gray-500 rounded px-3 py-2 text-sm w-52"
            />
            <datalist id="category-suggestions">
              {CATEGORIES.map((c) => <option key={c} value={c} />)}
            </datalist>
          </div>
          <SubmitButton className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-blue-500">
            Score Now
          </SubmitButton>
        </Form>
        <p className="text-xs text-gray-600 mt-2">
          Triggers GitHub Actions. Result appears below in ~2 min.
        </p>
      </section>

      <section className="bg-gray-800 border border-gray-700 rounded-lg p-5">
        <h2 className="font-semibold mb-4 text-gray-100">Score Trends</h2>
        <NicheScoreChart history={history} nicheNames={nicheNames} />
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

function ScoreBreakdown({ details }: { details: NicheScoreDetails }) {
  const items = [
    { label: 'RPM', value: `$${details.rpm}` },
    { label: 'Trend', value: `${details.trend}×` },
    { label: 'Reddit', value: `${details.reddit}/10` },
    { label: 'Comp', value: details.competition.toFixed(1) },
    ...(details.news > 0 ? [{ label: 'News', value: details.news.toFixed(2) }] : []),
  ]
  return (
    <div className="flex gap-3 mt-1.5">
      {items.map(({ label, value }) => (
        <span key={label} className="text-[10px] text-gray-500">
          <span className="text-gray-400">{label}</span> {value}
        </span>
      ))}
    </div>
  )
}

function NicheRow({ niche }: { niche: Niche }) {
  const isCandidate = niche.gate1_state === 'awaiting_review'
  return (
    <div className={`bg-gray-800 border rounded-lg p-4 flex items-start gap-4 ${isCandidate ? 'border-yellow-700/50' : 'border-gray-700'}`}>
      <div className="mt-0.5">
        <StatusPill status={niche.status} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="font-medium text-gray-100">{niche.name}</p>
        <p className="text-xs text-gray-500">
          {niche.category}
          {niche.niche_source === 'manual' ? ' · manual' : ''}
          {niche.score_details?.news && niche.score_details.news > 0 ? ' · news-driven' : ''}
        </p>
        {niche.score_details && <ScoreBreakdown details={niche.score_details} />}
      </div>
      <div className="flex items-center gap-3 flex-shrink-0">
        {niche.channel_state === 'linked' ? (
          <span className="text-xs text-green-400 border border-green-800 rounded px-2 py-0.5">
            {niche.youtube_accounts?.channel_name ?? 'Channel linked'}
          </span>
        ) : niche.status === 'promoted' ? (
          <span className="text-xs text-orange-400 border border-orange-800 rounded px-2 py-0.5">No channel</span>
        ) : null}
        {niche.score != null && <ScoreTooltip score={niche.score} />}
        <div className="flex gap-2">
          {isCandidate && (
            <>
              <Form action={activateNiche.bind(null, niche.id)} successMessage="Niche activated">
                <SubmitButton className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700 cursor-pointer">
                  Activate
                </SubmitButton>
              </Form>
              <Form action={dismissNiche.bind(null, niche.id)} successMessage="Niche dismissed">
                <SubmitButton className="bg-gray-700 text-gray-300 text-xs px-3 py-1.5 rounded hover:bg-gray-600 cursor-pointer">
                  Dismiss
                </SubmitButton>
              </Form>
            </>
          )}
          {niche.status === 'testing' && (
            <>
              <Form action={promoteNiche.bind(null, niche.id)} successMessage="Niche promoted">
                <SubmitButton className="text-green-400 text-xs px-3 py-1.5 rounded hover:bg-green-900/30 cursor-pointer">
                  Promote
                </SubmitButton>
              </Form>
              <Form action={archiveNiche.bind(null, niche.id)} successMessage="Niche archived">
                <SubmitButton className="text-red-400 text-xs px-3 py-1.5 rounded hover:bg-red-900/30 cursor-pointer">
                  Archive
                </SubmitButton>
              </Form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
