'use server'
import { revalidatePath } from 'next/cache'
import { createClient } from '@/lib/supabase/server'

export async function approveScript(id: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('scripts')
    .update({ gate3_state: 'approved' })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/scripts')
}

export async function rejectScript(id: string, reason: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('scripts')
    .update({ gate3_state: 'rejected', rejection_reason: reason })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/scripts')
}

export async function updateYoutubeTitle(id: string, title: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('scripts')
    .update({ youtube_title: title })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/scripts')
  revalidatePath('/media')
}

export async function deleteScript(id: string): Promise<void> {
  const supabase = await createClient()
  const { data: script, error: fetchError } = await supabase
    .from('scripts')
    .select('topic_id')
    .eq('id', id)
    .single()
  if (fetchError) throw new Error(fetchError.message)
  await supabase.from('videos').delete().eq('script_id', id)
  const { error: deleteError } = await supabase.from('scripts').delete().eq('id', id)
  if (deleteError) throw new Error(deleteError.message)
  if (script?.topic_id) {
    await supabase
      .from('topics')
      .update({ gate2_state: 'rejected' })
      .eq('id', script.topic_id)
  }
  revalidatePath('/scripts')
  revalidatePath('/topics')
}

export async function updateScript(
  id: string,
  longFormText: string,
  shortText: string,
  youtubeTitle: string
): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('scripts')
    .update({ long_form_text: longFormText, short_text: shortText, youtube_title: youtubeTitle })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/scripts')
}
