import { createClient } from '@/lib/supabase/server'
import type { PublishedVideo, PublishedVideoStatus } from '@/lib/types'

type Row = PublishedVideo & { niches: { name: string } }

function StatusBadge({ status }: { status: PublishedVideoStatus }) {
  const styles: Record<PublishedVideoStatus, string> = {
    live: 'bg-green-100 text-green-800',
    removed: 'bg-red-100 text-red-800',
    private: 'bg-yellow-100 text-yellow-800',
  }
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${styles[status]}`}>
      {status}
    </span>
  )
}

function TypeBadge({ type }: { type: 'long' | 'short' }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
      type === 'long' ? 'bg-blue-100 text-blue-800' : 'bg-purple-100 text-purple-800'
    }`}>
      {type}
    </span>
  )
}

function fmtDate(ts: string) {
  return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function fmtDur(sec: number | null) {
  if (!sec) return '—'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

export default async function VideosPage() {
  const supabase = await createClient()

  const { data: rows } = await supabase
    .from('published_videos')
    .select('*, niches(name)')
    .order('uploaded_at', { ascending: false })

  const videos = (rows ?? []) as Row[]

  const live = videos.filter((v) => v.status === 'live').length
  const removed = videos.filter((v) => v.status === 'removed').length
  const priv = videos.filter((v) => v.status === 'private').length

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">Published Videos</h1>
      <p className="text-sm text-gray-500 mb-6">
        Synced against YouTube on each analytics run. Status reflects current YouTube state.
      </p>

      <div className="flex gap-4 mb-6">
        <div className="bg-white border rounded-lg px-4 py-3 text-center min-w-[90px]">
          <div className="text-2xl font-bold text-green-700">{live}</div>
          <div className="text-xs text-gray-500 mt-0.5">Live</div>
        </div>
        <div className="bg-white border rounded-lg px-4 py-3 text-center min-w-[90px]">
          <div className="text-2xl font-bold text-red-700">{removed}</div>
          <div className="text-xs text-gray-500 mt-0.5">Removed</div>
        </div>
        <div className="bg-white border rounded-lg px-4 py-3 text-center min-w-[90px]">
          <div className="text-2xl font-bold text-yellow-700">{priv}</div>
          <div className="text-xs text-gray-500 mt-0.5">Private</div>
        </div>
        <div className="bg-white border rounded-lg px-4 py-3 text-center min-w-[90px]">
          <div className="text-2xl font-bold text-gray-700">{videos.length}</div>
          <div className="text-xs text-gray-500 mt-0.5">Total</div>
        </div>
      </div>

      <div className="bg-white border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Title</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Niche</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Type</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Duration</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Uploaded</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">YouTube</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {videos.map((v) => (
              <tr key={v.id} className={`hover:bg-gray-50 ${v.status === 'removed' ? 'opacity-60' : ''}`}>
                <td className="px-4 py-3 max-w-xs">
                  <span className="line-clamp-2 text-gray-900">{v.title ?? v.youtube_video_id}</span>
                </td>
                <td className="px-4 py-3 text-gray-600 whitespace-nowrap">{v.niches?.name ?? '—'}</td>
                <td className="px-4 py-3"><TypeBadge type={v.video_type} /></td>
                <td className="px-4 py-3 text-gray-600 whitespace-nowrap">{fmtDur(v.duration_sec)}</td>
                <td className="px-4 py-3 text-gray-600 whitespace-nowrap">{fmtDate(v.uploaded_at)}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={v.status} />
                  {v.removed_at && (
                    <div className="text-xs text-gray-400 mt-0.5">{fmtDate(v.removed_at)}</div>
                  )}
                </td>
                <td className="px-4 py-3">
                  {v.status !== 'removed' ? (
                    <a
                      href={`https://youtube.com/watch?v=${v.youtube_video_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline cursor-pointer"
                    >
                      Watch
                    </a>
                  ) : (
                    <span className="text-gray-400 text-xs">Unavailable</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {videos.length === 0 && (
          <div className="px-4 py-8 text-center text-gray-400">No published videos yet.</div>
        )}
      </div>
    </div>
  )
}
