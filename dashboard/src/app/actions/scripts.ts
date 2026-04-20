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
