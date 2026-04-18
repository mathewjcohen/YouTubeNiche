import { createClient } from '@/lib/supabase/server'
import { approveMedia, rejectMedia } from '@/app/actions/media'
import type { Video } from '@/lib/types'

const GATE_LABELS: Record<4 | 5 | 6, string> = {
  4: 'Voiceover',
  5: 'Thumbnail',
  6: 'Final Video',
}

export default async function MediaPage() {
  const supabase = await createClient()
  const { data: videos } = await supabase
    .from('videos')
    .select('*, scripts(youtube_title, long_form_text), niches(name)')
    .or('gate4_state.eq.awaiting_review,gate5_state.eq.awaiting_review,gate6_state.eq.awaiting_review')
    .order('created_at')

  const total = videos?.length ?? 0

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">Media Review</h1>
      <p className="text-sm text-gray-400 mb-6">Gates 4/5/6 — {total} awaiting review</p>

      {!total ? (
        <p className="text-gray-500">Queue is empty.</p>
      ) : (
        <div className="space-y-4">
          {(videos as (Video & { scripts: { youtube_title: string | null; long_form_text: string }; niches: { name: string } })[]).map((v) => (
            <MediaCard key={v.id} video={v} />
          ))}
        </div>
      )}
    </div>
  )
}

function MediaCard({ video }: {
  video: Video & { scripts: { youtube_title: string | null; long_form_text: string }; niches: { name: string } }
}) {
  const pendingGates = ([4, 5, 6] as const).filter(
    (g) => video[`gate${g}_state`] === 'awaiting_review'
  )

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5">
      <div className="flex gap-5">
        <div className="w-40 h-24 bg-gray-100 rounded overflow-hidden shrink-0 flex items-center justify-center">
          {video.thumbnail_path?.startsWith('http') ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={video.thumbnail_path} alt="thumbnail" className="object-cover w-full h-full" />
          ) : (
            <span className="text-xs text-gray-400">No preview</span>
          )}
        </div>

        <div className="flex-1">
          <p className="font-semibold">{video.scripts?.youtube_title ?? '—'}</p>
          <p className="text-xs text-gray-400">{video.niches?.name}</p>

          <div className="flex gap-3 mt-3">
            {pendingGates.map((gate) => (
              <div key={gate} className="border border-orange-300 rounded p-3 bg-orange-50">
                <p className="text-xs font-semibold text-orange-700 mb-2">Gate {gate} — {GATE_LABELS[gate]}</p>
                <div className="flex gap-2">
                  <form action={approveMedia.bind(null, video.id, gate)}>
                    <button className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700">
                      Approve
                    </button>
                  </form>
                  <form action={async (fd: FormData) => {
                    'use server'
                    await rejectMedia(video.id, gate, fd.get('reason') as string || 'Rejected')
                  }}>
                    <input name="reason" placeholder="Reason" className="border border-gray-200 rounded px-2 py-1 text-xs w-32" />
                    <button className="bg-gray-200 text-gray-700 text-xs px-3 py-1.5 rounded hover:bg-gray-300 ml-1">
                      Reject
                    </button>
                  </form>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
