'use client'
import { useState, useTransition } from 'react'
import { approveScript, rejectScript, updateScript } from '@/app/actions/scripts'
import type { Script } from '@/lib/types'

export function ScriptReviewClient({ script }: { script: Script & { niches: { name: string } } }) {
  const [longForm, setLongForm] = useState(script.long_form_text)
  const [short, setShort] = useState(script.short_text)
  const [reason, setReason] = useState('')
  const [pending, startTransition] = useTransition()

  const approve = () => startTransition(async () => {
    if (longForm !== script.long_form_text || short !== script.short_text) {
      await updateScript(script.id, longForm, short)
    }
    await approveScript(script.id)
  })

  const reject = () => startTransition(() => rejectScript(script.id, reason || 'Rejected'))

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
      <div className="flex items-center gap-2">
        <span className="font-semibold text-sm">{script.niches?.name}</span>
        <span className="text-xs text-gray-400">{new Date(script.created_at).toLocaleDateString()}</span>
      </div>

      {script.youtube_title && (
        <p className="text-sm font-medium text-blue-700">Title: {script.youtube_title}</p>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="text-xs text-gray-500 mb-1 font-semibold">Long-form (~12 min)</p>
          <textarea
            value={longForm}
            onChange={(e) => setLongForm(e.target.value)}
            className="w-full h-64 border border-gray-200 rounded p-2 text-sm font-mono resize-y"
          />
        </div>
        <div>
          <p className="text-xs text-gray-500 mb-1 font-semibold">Short (~60 sec)</p>
          <textarea
            value={short}
            onChange={(e) => setShort(e.target.value)}
            className="w-full h-64 border border-gray-200 rounded p-2 text-sm font-mono resize-y"
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={approve}
          disabled={pending}
          className="bg-green-600 text-white px-4 py-2 rounded text-sm hover:bg-green-700 disabled:opacity-50"
        >
          Approve{longForm !== script.long_form_text || short !== script.short_text ? ' (with edits)' : ''}
        </button>
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Rejection reason"
          className="border border-gray-200 rounded px-3 py-2 text-sm flex-1"
        />
        <button
          onClick={reject}
          disabled={pending}
          className="bg-gray-200 text-gray-700 px-4 py-2 rounded text-sm hover:bg-gray-300 disabled:opacity-50"
        >
          Reject
        </button>
      </div>
    </div>
  )
}
