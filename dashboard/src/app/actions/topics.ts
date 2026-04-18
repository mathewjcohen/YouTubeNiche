'use server'
import { revalidatePath } from 'next/cache'
import { createClient } from '@/lib/supabase/server'

export async function approveTopic(id: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('topics')
    .update({ gate2_state: 'approved' })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/topics')
}

export async function rejectTopic(id: string, reason: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('topics')
    .update({ gate2_state: 'rejected', rejection_reason: reason })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/topics')
}
