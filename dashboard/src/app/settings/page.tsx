import { createClient } from '@/lib/supabase/server'
import { saveGateConfig } from '@/app/actions/settings'
import type { GateConfig, Niche } from '@/lib/types'

const GATE_LABELS: Record<number, string> = {
  1: 'Niche Activation',
  2: 'Topic Selection',
  3: 'Script',
  4: 'Voiceover',
  5: 'Thumbnail',
  6: 'Final Video',
}

const DEFAULT_ON = new Set([1, 3, 5, 6])

export default async function SettingsPage() {
  const supabase = await createClient()

  const [{ data: niches }, { data: configs }] = await Promise.all([
    supabase.from('niches').select('id, name').in('status', ['testing', 'promoted']).order('name'),
    supabase.from('gate_config').select('*'),
  ])

  const getConfig = (nicheId: string | null, gate: number): boolean => {
    const row = (configs as GateConfig[] | null)?.find(
      (c) => c.gate_number === gate && c.niche_id === nicheId
    )
    if (row) return row.gate_enabled
    const globalRow = (configs as GateConfig[] | null)?.find(
      (c) => c.gate_number === gate && c.niche_id === null
    )
    return globalRow ? globalRow.gate_enabled : DEFAULT_ON.has(gate)
  }

  const scopes = [
    { id: null, label: 'Global defaults' },
    ...((niches as Niche[] | null) ?? []).map((n) => ({ id: n.id, label: n.name })),
  ]

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Settings</h1>
      <div className="space-y-6">
        {scopes.map((scope) => (
          <div key={scope.id ?? 'global'} className="bg-white border border-gray-200 rounded-lg p-5">
            <h2 className="font-semibold mb-4">{scope.label}</h2>
            <form action={saveGateConfig}>
              <input type="hidden" name="niche_id" value={scope.id ?? ''} />
              <div className="grid grid-cols-3 gap-4 mb-4">
                {[1, 2, 3, 4, 5, 6].map((gate) => {
                  const enabled = getConfig(scope.id, gate)
                  return (
                    <label key={gate} className="flex items-center justify-between border border-gray-100 rounded p-3">
                      <span className="text-sm">
                        <span className="font-medium">Gate {gate}</span>
                        <span className="text-gray-400 ml-1">— {GATE_LABELS[gate]}</span>
                      </span>
                      <input
                        type="checkbox"
                        name={`gate${gate}`}
                        defaultChecked={enabled}
                        value="on"
                        className="w-4 h-4 accent-orange-500"
                      />
                    </label>
                  )
                })}
              </div>
              <button
                type="submit"
                className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700"
              >
                Save
              </button>
            </form>
          </div>
        ))}
      </div>
    </div>
  )
}
