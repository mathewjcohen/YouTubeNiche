import { createClient } from '@/lib/supabase/server'
import { ScriptReviewClient } from './script-review-client'
import type { Script } from '@/lib/types'

export default async function ScriptsPage() {
  const supabase = await createClient()
  const { data: scripts } = await supabase
    .from('scripts')
    .select('*, niches(name)')
    .eq('gate3_state', 'awaiting_review')
    .order('created_at')

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">Script Review</h1>
      <p className="text-sm text-gray-400 mb-6">Gate 3 — {scripts?.length ?? 0} awaiting review</p>
      {!scripts?.length ? (
        <p className="text-gray-500">Queue is empty.</p>
      ) : (
        <div className="space-y-6">
          {scripts.map((s) => (
            <ScriptReviewClient key={s.id} script={s as Script & { niches: { name: string } }} />
          ))}
        </div>
      )}
    </div>
  )
}
