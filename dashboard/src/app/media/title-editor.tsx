'use client'
import { useState, useTransition } from 'react'
import { toast } from 'sonner'
import { updateYoutubeTitle } from '@/app/actions/scripts'

export function TitleEditor({ scriptId, initialTitle }: { scriptId: string; initialTitle: string | null }) {
  const [title, setTitle] = useState(initialTitle ?? '')
  const [pending, startTransition] = useTransition()

  const save = () => startTransition(async () => {
    try {
      await updateYoutubeTitle(scriptId, title)
      toast.success('Title saved')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Something went wrong')
    }
  })

  const dirty = title !== (initialTitle ?? '')

  return (
    <div className="flex items-center gap-2 mb-1">
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="flex-1 border border-gray-600 bg-gray-700 text-gray-100 rounded px-2 py-1 text-sm font-semibold focus:border-gray-400 outline-none"
        placeholder="YouTube title"
      />
      {dirty && (
        <button
          onClick={save}
          disabled={pending}
          className="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-700 disabled:opacity-50 shrink-0"
        >
          Save
        </button>
      )}
    </div>
  )
}
