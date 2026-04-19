'use server'
import { revalidatePath } from 'next/cache'
import { createClient } from '@/lib/supabase/server'
import { toggleGate } from './gates'

export async function saveGateConfig(formData: FormData): Promise<void> {
  const nicheId = formData.get('niche_id') as string | null || null
  const updates: Array<{ gate: number; enabled: boolean }> = []

  for (let gate = 1; gate <= 6; gate++) {
    const value = formData.get(`gate${gate}`)
    updates.push({ gate, enabled: value === 'on' })
  }

  await Promise.all(updates.map(({ gate, enabled }) => toggleGate(gate, nicheId, enabled)))
  revalidatePath('/settings')
}

export async function setRenderMethod(formData: FormData): Promise<void> {
  const method = formData.get('render_method') as string
  if (method !== 'github' && method !== 'aws') return
  const supabase = await createClient()
  await supabase
    .from('app_settings')
    .upsert({ key: 'render_method', value: method }, { onConflict: 'key' })
  revalidatePath('/settings')
}
