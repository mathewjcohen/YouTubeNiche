'use server'
import { revalidatePath } from 'next/cache'
import { createClient } from '@/lib/supabase/server'

type MediaGate = 4 | 5 | 6

function gateColumn(gate: MediaGate): string {
  return `gate${gate}_state`
}

function rejectionColumn(gate: MediaGate): string {
  return `gate${gate}_rejection_reason`
}

export async function approveMedia(id: string, gate: MediaGate): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('videos')
    .update({ [gateColumn(gate)]: 'approved' })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/media')
}

export async function rejectMedia(id: string, gate: MediaGate, reason: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('videos')
    .update({ [gateColumn(gate)]: 'rejected', [rejectionColumn(gate)]: reason })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/media')
}
