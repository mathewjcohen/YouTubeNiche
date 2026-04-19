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
  const update: Record<string, string> = { [gateColumn(gate)]: 'approved' }
  // Gate 6 is the final approval — mark video ready for upload
  if (gate === 6) update.status = 'approved'
  const { error } = await supabase.from('videos').update(update).eq('id', id)
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

export async function retryThumbnail(id: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('videos')
    .update({ thumbnail_path: null, gate5_state: 'awaiting_review' })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/media')
}

export async function approveGate5ForScript(scriptId: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('videos')
    .update({ gate5_state: 'approved' })
    .eq('script_id', scriptId)
  if (error) throw new Error(error.message)
  revalidatePath('/media')
}

export async function rejectGate5ForScript(scriptId: string, reason: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('videos')
    .update({ gate5_state: 'rejected', gate5_rejection_reason: reason })
    .eq('script_id', scriptId)
  if (error) throw new Error(error.message)
  revalidatePath('/media')
}

export async function retryThumbnailForScript(scriptId: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('videos')
    .update({ thumbnail_path: null, gate5_state: 'awaiting_review' })
    .eq('script_id', scriptId)
  if (error) throw new Error(error.message)
  revalidatePath('/media')
}
