import { createClient } from '@/lib/supabase/server'
import { saveGateConfig, setRenderMethod, setPipelineEnabled } from '@/app/actions/settings'
import { Form, SubmitButton } from '@/components/form'
import { Collapsible } from '@/components/collapsible'
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

  const [{ data: niches }, { data: configs }, { data: appSettings }] = await Promise.all([
    supabase.from('niches').select('id, name').in('status', ['testing', 'promoted']).order('name'),
    supabase.from('gate_config').select('*'),
    supabase.from('app_settings').select('key, value'),
  ])

  const settings = appSettings as { key: string; value: string }[] | null
  const renderMethod = settings?.find((s) => s.key === 'render_method')?.value ?? 'github'
  const pipelineEnabled = (settings?.find((s) => s.key === 'pipeline_enabled')?.value ?? 'true') === 'true'

  const getConfig = (nicheId: string | null, gate: number): boolean => {
    const row = (configs as GateConfig[] | null)?.find(
      (c) => c.gate_number === gate && c.niche_id === nicheId
    )
    if (row) return row.enabled
    const globalRow = (configs as GateConfig[] | null)?.find(
      (c) => c.gate_number === gate && c.niche_id === null
    )
    return globalRow ? globalRow.enabled : DEFAULT_ON.has(gate)
  }

  const scopes = [
    { id: null, label: 'Global defaults' },
    ...((niches as Niche[] | null) ?? []).map((n) => ({ id: n.id, label: n.name })),
  ]

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      <div className={`border rounded-lg p-5 mb-6 ${pipelineEnabled ? 'bg-gray-800 border-gray-700' : 'bg-red-950/30 border-red-800/60'}`}>
        <div className="flex items-center justify-between mb-1">
          <h2 className="font-semibold text-gray-100">Pipeline</h2>
          <span className={`text-xs font-medium px-2 py-0.5 rounded ${pipelineEnabled ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
            {pipelineEnabled ? 'Running' : 'Paused'}
          </span>
        </div>
        <p className="text-xs text-gray-500 mb-4">Pausing disables the pipeline_runner GitHub Actions workflow — no scheduled runs will fire. Resume re-enables it.</p>
        <Form action={setPipelineEnabled} successMessage={pipelineEnabled ? 'Pipeline paused' : 'Pipeline resumed'}>
          <input type="hidden" name="pipeline_enabled" value={pipelineEnabled ? 'false' : 'true'} />
          <SubmitButton
            className={`px-4 py-2 rounded text-sm font-medium ${pipelineEnabled ? 'bg-red-700 hover:bg-red-600 text-white' : 'bg-green-700 hover:bg-green-600 text-white'}`}
          >
            {pipelineEnabled ? 'Pause Pipeline' : 'Resume Pipeline'}
          </SubmitButton>
        </Form>
      </div>

      <div className="bg-gray-800 border border-gray-700 rounded-lg p-5 mb-6">
        <h2 className="font-semibold mb-1 text-gray-100">Video Render Method</h2>
        <p className="text-xs text-gray-500 mb-4">GitHub extended timeout runs assembly on a 350-min runner. AWS (Remotion Lambda) offloads rendering to Lambda once configured.</p>
        <Form action={setRenderMethod} successMessage="Render method saved" className="flex gap-3 items-center">
          <label className={`flex items-center gap-2 border rounded px-4 py-2 cursor-pointer text-sm ${renderMethod === 'github' ? 'border-orange-500 bg-orange-900/20 text-orange-300' : 'border-gray-700 text-gray-400 hover:border-gray-600'}`}>
            <input type="radio" name="render_method" value="github" defaultChecked={renderMethod === 'github'} className="accent-orange-500" />
            GitHub (extended timeout)
          </label>
          <label className={`flex items-center gap-2 border rounded px-4 py-2 cursor-pointer text-sm ${renderMethod === 'aws' ? 'border-orange-500 bg-orange-900/20 text-orange-300' : 'border-gray-700 text-gray-400 hover:border-gray-600'}`}>
            <input type="radio" name="render_method" value="aws" defaultChecked={renderMethod === 'aws'} className="accent-orange-500" />
            AWS (Remotion Lambda)
          </label>
          <SubmitButton className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-500">
            Save
          </SubmitButton>
        </Form>
      </div>

      <div className="space-y-3">
        {scopes.map((scope) => {
          const isGlobal = scope.id === null
          return (
            <div key={scope.id ?? 'global'} className="bg-gray-800 border border-gray-700 rounded-lg">
              <Collapsible
                defaultOpen={isGlobal}
                className="p-5"
                title={
                  <h2 className="font-semibold text-gray-100">{scope.label}</h2>
                }
              >
                <Form action={saveGateConfig} successMessage="Gate config saved" className="mt-4">
                  <input type="hidden" name="niche_id" value={scope.id ?? ''} />
                  <div className="grid grid-cols-3 gap-4 mb-4">
                    {[1, 2, 3, 4, 5, 6].map((gate) => {
                      const enabled = getConfig(scope.id, gate)
                      return (
                        <label key={gate} className="flex items-center justify-between border border-gray-700 rounded p-3 hover:border-gray-600">
                          <span className="text-sm text-gray-300">
                            <span className="font-medium">Gate {gate}</span>
                            <span className="text-gray-500 ml-1">— {GATE_LABELS[gate]}</span>
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
                  <SubmitButton className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-500">
                    Save
                  </SubmitButton>
                </Form>
              </Collapsible>
            </div>
          )
        })}
      </div>
    </div>
  )
}
