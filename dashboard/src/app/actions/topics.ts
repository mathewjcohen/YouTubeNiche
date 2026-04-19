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

export async function approveTopBatch(formData: FormData): Promise<void> {
  const raw = parseInt(formData.get('count') as string, 10)
  const count = Number.isFinite(raw) ? Math.max(1, Math.min(20, raw)) : 5
  const supabase = await createClient()
  const { data: topics } = await supabase
    .from('topics')
    .select('id')
    .eq('gate2_state', 'awaiting_review')
    .eq('status', 'pending')
    .order('claude_score', { ascending: false })
    .limit(count)
  if (!topics?.length) return
  const { error } = await supabase
    .from('topics')
    .update({ gate2_state: 'approved' })
    .in('id', topics.map((t) => t.id))
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
