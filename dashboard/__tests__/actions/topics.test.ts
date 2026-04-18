jest.mock('@/lib/supabase/server', () => ({ createClient: jest.fn() }))
jest.mock('next/cache', () => ({ revalidatePath: jest.fn() }))

import { createClient } from '@/lib/supabase/server'
import { approveTopic, rejectTopic } from '@/app/actions/topics'

const mockUpdate = jest.fn().mockReturnThis()
const mockEq = jest.fn().mockResolvedValue({ error: null })
const mockSupabase = { from: jest.fn().mockReturnValue({ update: mockUpdate, eq: mockEq }) }

beforeEach(() => {
  jest.clearAllMocks()
  ;(createClient as jest.Mock).mockResolvedValue(mockSupabase)
  mockUpdate.mockReturnValue({ eq: mockEq })
})

test('approveTopic sets gate2_state to approved', async () => {
  await approveTopic('topic-1')
  expect(mockUpdate).toHaveBeenCalledWith({ gate2_state: 'approved' })
  expect(mockEq).toHaveBeenCalledWith('id', 'topic-1')
})

test('rejectTopic sets gate2_state to rejected with reason', async () => {
  await rejectTopic('topic-1', 'Too generic')
  expect(mockUpdate).toHaveBeenCalledWith({ gate2_state: 'rejected', rejection_reason: 'Too generic' })
})
