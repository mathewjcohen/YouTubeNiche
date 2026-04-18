'use server'
import { revalidatePath } from 'next/cache'
import { createClient } from '@/lib/supabase/server'

export async function activateNiche(id: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('niches')
    .update({ gate1_state: 'approved', status: 'testing', activated_at: new Date().toISOString() })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/niches')
}

export async function dismissNiche(id: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('niches')
    .update({ gate1_state: 'rejected', status: 'archived' })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/niches')
}

export async function archiveNiche(id: string): Promise<void> {
  const supabase = await createClient()
  const { error } = await supabase
    .from('niches')
    .update({ status: 'archived' })
    .eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/niches')
}

export async function submitManualNiche(formData: FormData): Promise<void> {
  const nicheName = formData.get('niche_name') as string
  const category = formData.get('category') as string
  if (!nicheName || !category) throw new Error('niche_name and category are required')

  const res = await fetch(
    `https://api.github.com/repos/${process.env.GITHUB_REPO}/actions/workflows/manual_niche_score.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${process.env.GITHUB_PAT}`,
        Accept: 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main', inputs: { niche_name: nicheName, category } }),
    }
  )
  if (!res.ok) throw new Error(`GitHub API error: ${res.status}`)
  revalidatePath('/niches')
}
