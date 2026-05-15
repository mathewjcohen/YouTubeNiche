jest.mock('@/lib/supabase/server', () => ({ createClient: jest.fn() }))
jest.mock('next/cache', () => ({ revalidatePath: jest.fn() }))

import { createClient } from '@/lib/supabase/server'
import { revalidatePath } from 'next/cache'
import { setTopicRunnerEnabled } from '@/app/actions/settings'

const mockUpsert = jest.fn().mockResolvedValue({ error: null })
const mockFrom = jest.fn().mockReturnValue({ upsert: mockUpsert })
const mockSupabase = { from: mockFrom }

beforeEach(() => {
  jest.clearAllMocks()
  ;(createClient as jest.Mock).mockResolvedValue(mockSupabase)
})

test('setTopicRunnerEnabled saves false when value is false', async () => {
  const fd = new FormData()
  fd.set('topic_runner_enabled', 'false')
  await setTopicRunnerEnabled(fd)
  expect(mockUpsert).toHaveBeenCalledWith(
    { key: 'topic_runner_enabled', value: 'false' },
    { onConflict: 'key' }
  )
  expect(revalidatePath).toHaveBeenCalledWith('/topics')
})

test('setTopicRunnerEnabled saves true when value is true', async () => {
  const fd = new FormData()
  fd.set('topic_runner_enabled', 'true')
  await setTopicRunnerEnabled(fd)
  expect(mockUpsert).toHaveBeenCalledWith(
    { key: 'topic_runner_enabled', value: 'true' },
    { onConflict: 'key' }
  )
})

test('setTopicRunnerEnabled throws when upsert fails', async () => {
  const fd = new FormData()
  fd.set('topic_runner_enabled', 'true')
  mockUpsert.mockResolvedValueOnce({ error: { message: 'Database error' } })
  await expect(setTopicRunnerEnabled(fd)).rejects.toThrow('Database error')
})
