import type { NicheStatus } from '@/lib/types'

const COLORS: Record<NicheStatus, string> = {
  candidate: 'bg-gray-700 text-gray-300',
  testing: 'bg-yellow-900/40 text-yellow-300',
  promoted: 'bg-green-900/40 text-green-300',
  archived: 'bg-red-900/40 text-red-300',
}

export function StatusPill({ status }: { status: NicheStatus }) {
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${COLORS[status]}`}>
      {status}
    </span>
  )
}
