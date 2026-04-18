'use client'
import { useTransition } from 'react'

interface Props {
  gateNumber: number
  nicheId: string | null
  enabled: boolean
  onToggle: (gateNumber: number, nicheId: string | null, enabled: boolean) => Promise<void>
}

export function GateToggle({ gateNumber, nicheId, enabled, onToggle }: Props) {
  const [pending, startTransition] = useTransition()

  return (
    <button
      disabled={pending}
      onClick={() => startTransition(() => onToggle(gateNumber, nicheId, !enabled))}
      className={`px-3 py-1 rounded text-sm font-semibold transition-colors ${
        enabled
          ? 'bg-orange-500 text-white hover:bg-orange-600'
          : 'bg-gray-200 text-gray-600 hover:bg-gray-300'
      } disabled:opacity-50`}
    >
      {enabled ? 'ON' : 'OFF'}
    </button>
  )
}
