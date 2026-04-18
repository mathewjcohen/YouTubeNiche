'use server'
import { revalidatePath } from 'next/cache'
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
