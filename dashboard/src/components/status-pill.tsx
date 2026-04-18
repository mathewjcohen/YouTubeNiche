import type { NicheStatus } from '@/lib/types'

const COLORS: Record<NicheStatus, string> = {
  candidate: 'bg-gray-100 text-gray-700',
  testing: 'bg-yellow-100 text-yellow-800',
  promoted: 'bg-green-100 text-green-800',
  archived: 'bg-red-100 text-red-700',
}

export function StatusPill({ status }: { status: NicheStatus }) {
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${COLORS[status]}`}>
      {status}
    </span>
  )
}
