jest.mock('@/lib/supabase/server', () => ({
  createClient: jest.fn(),
}))

jest.mock('next/cache', () => ({
  revalidatePath: jest.fn(),
}))

import { createClient } from '@/lib/supabase/server'
import { toggleGate, getGateConfig } from '@/app/actions/gates'

const mockSupabase = {
  from: jest.fn().mockReturnThis(),
  select: jest.fn().mockReturnThis(),
  eq: jest.fn().mockReturnThis(),
  update: jest.fn().mockReturnThis(),
  upsert: jest.fn().mockReturnThis(),
  single: jest.fn(),
  is: jest.fn().mockReturnThis(),
}

beforeEach(() => {
  jest.clearAllMocks()
  ;(createClient as jest.Mock).mockResolvedValue(mockSupabase)
})

test('toggleGate calls upsert with correct payload', async () => {
  mockSupabase.upsert.mockResolvedValue({ error: null })
  await toggleGate(3, null, false)
  expect(mockSupabase.upsert).toHaveBeenCalledWith(
    expect.objectContaining({ gate_number: 3, niche_id: null, gate_enabled: false }),
    expect.anything()
  )
})

test('getGateConfig returns gate_enabled for given gate + niche', async () => {
  mockSupabase.single.mockResolvedValue({
    data: { gate_enabled: true },
    error: null,
  })
  const result = await getGateConfig(3, 'niche-1')
  expect(result).toBe(true)
})
