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
  if (gate === 5) update.gate6_state = 'awaiting_review'
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

export async function returnToScript(videoId: string): Promise<void> {
  const supabase = await createClient()
  const { data: video, error: fetchErr } = await supabase
    .from('videos')
    .select('script_id')
    .eq('id', videoId)
    .single()
  if (fetchErr || !video) throw new Error(fetchErr?.message ?? 'Video not found')
  const { error: delError } = await supabase.from('videos').delete().eq('id', videoId)
  if (delError) throw new Error(delError.message)
  const { error: updError } = await supabase
    .from('scripts')
    .update({ gate3_state: 'awaiting_review', status: 'approved' })
    .eq('id', video.script_id)
  if (updError) throw new Error(updError.message)
  revalidatePath('/media')
  revalidatePath('/scripts')
}

export async function retryVoiceover(videoId: string): Promise<void> {
  const supabase = await createClient()
  // Look up which script this video belongs to
  const { data: video, error: fetchErr } = await supabase
    .from('videos')
    .select('script_id')
    .eq('id', videoId)
    .single()
  if (fetchErr || !video) throw new Error(fetchErr?.message ?? 'Video not found')
  // Delete just this video row — the agent's idempotency guard will skip the sibling
  const { error: delError } = await supabase.from('videos').delete().eq('id', videoId)
  if (delError) throw new Error(delError.message)
  // Reset script so the voiceover stage picks it up again
  const { error: updError } = await supabase
    .from('scripts')
    .update({ status: 'pending' })
    .eq('id', video.script_id)
  if (updError) throw new Error(updError.message)
  revalidatePath('/media')
}

export async function retryVideoAssembly(videoId: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('videos')
    .update({ video_path: null, gate4_state: 'approved', gate6_state: 'pending', status: 'pending' })
    .eq('id', videoId)
  if (error) throw new Error(error.message)
  revalidatePath('/media')
}
