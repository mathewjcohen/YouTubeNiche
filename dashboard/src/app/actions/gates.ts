'use server'
import { revalidatePath } from 'next/cache'
import { createClient } from '@/lib/supabase/server'

export async function toggleGate(
  gateNumber: number,
  nicheId: string | null,
  enabled: boolean
): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase.from('gate_config').upsert(
    { gate_number: gateNumber, niche_id: nicheId, enabled },
    { onConflict: 'gate_number,niche_id' }
  )
  if (error) throw new Error(error.message)
  revalidatePath('/', 'layout')
}

export async function getGateConfig(
  gateNumber: number,
  nicheId: string | null
): Promise<boolean> {
  const supabase = await createClient()
  const DEFAULT_ON = [1, 3, 5, 6]

  if (nicheId) {
    const { data } = await supabase
      .from('gate_config')
      .select('enabled')
      .eq('gate_number', gateNumber)
      .eq('niche_id', nicheId)
      .single()
    if (data) return data.enabled
  }

  const { data } = await supabase
    .from('gate_config')
    .select('enabled')
    .eq('gate_number', gateNumber)
    .is('niche_id', null)
    .single()
  return data ? data.enabled : DEFAULT_ON.includes(gateNumber)
}
