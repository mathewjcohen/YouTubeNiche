jest.mock('@/lib/supabase/server', () => ({ createClient: jest.fn() }))
jest.mock('next/cache', () => ({ revalidatePath: jest.fn() }))

import { createClient } from '@/lib/supabase/server'
import { approveScript, rejectScript, updateScript } from '@/app/actions/scripts'

const mockEq = jest.fn().mockResolvedValue({ error: null })
const mockUpdate = jest.fn().mockReturnValue({ eq: mockEq })
const mockSupabase = { from: jest.fn().mockReturnValue({ update: mockUpdate }) }

beforeEach(() => {
  jest.clearAllMocks()
  ;(createClient as jest.Mock).mockResolvedValue(mockSupabase)
})

test('approveScript sets gate3_state to approved', async () => {
  await approveScript('script-1')
  expect(mockUpdate).toHaveBeenCalledWith({ gate3_state: 'approved' })
})

test('rejectScript includes rejection_reason', async () => {
  await rejectScript('script-1', 'Too promotional')
  expect(mockUpdate).toHaveBeenCalledWith(
    expect.objectContaining({ gate3_state: 'rejected', rejection_reason: 'Too promotional' })
  )
})

test('updateScript patches long_form_text and short_text', async () => {
  await updateScript('script-1', 'new long form', 'new short')
  expect(mockUpdate).toHaveBeenCalledWith({ long_form_text: 'new long form', short_text: 'new short' })
})
