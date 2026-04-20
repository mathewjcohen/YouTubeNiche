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

export async function approveTopBatchPerNiche(formData: FormData): Promise<void> {
  const raw = parseInt(formData.get('count') as string, 10)
  const count = Number.isFinite(raw) ? Math.max(1, Math.min(20, raw)) : 3
  const supabase = await createClient()
  const { data: topics } = await supabase
    .from('topics')
    .select('id, niche_id')
    .eq('gate2_state', 'awaiting_review')
    .eq('status', 'pending')
    .order('claude_score', { ascending: false })
  if (!topics?.length) return
  // Take top N per niche from the already score-sorted list
  const perNiche = new Map<string, number>()
  const ids: string[] = []
  for (const t of topics) {
    const seen = perNiche.get(t.niche_id) ?? 0
    if (seen < count) {
      ids.push(t.id)
      perNiche.set(t.niche_id, seen + 1)
    }
  }
  if (!ids.length) return
  const { error } = await supabase
    .from('topics')
    .update({ gate2_state: 'approved' })
    .in('id', ids)
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
