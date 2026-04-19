import { createClient } from '@/lib/supabase/server'
import { approveMedia, rejectMedia, approveGate5ForScript, rejectGate5ForScript, retryThumbnailForScript } from '@/app/actions/media'
import type { Video } from '@/lib/types'

const GATE_LABELS: Record<4 | 5 | 6, string> = {
  4: 'Voiceover',
  5: 'Thumbnail',
  6: 'Final Video',
}

type VideoRow = Video & {
  scripts: { youtube_title: string | null; long_form_text: string }
  niches: { name: string }
}

type ScriptGroup = {
  scriptId: string
  title: string | null
  nicheName: string
  longThumbnail: string | null | undefined
  shortThumbnail: string | null | undefined
  showGate5: boolean
  videos: VideoRow[]
}

function groupByScript(videos: VideoRow[]): ScriptGroup[] {
  const map = new Map<string, VideoRow[]>()
  for (const v of videos) {
    const existing = map.get(v.script_id) ?? []
    map.set(v.script_id, [...existing, v])
  }
  return Array.from(map.values()).map((group) => ({
    scriptId: group[0].script_id,
    title: group[0].scripts?.youtube_title ?? null,
    nicheName: group[0].niches?.name ?? '',
    longThumbnail: group.find((v) => v.video_type === 'long' && v.thumbnail_path?.startsWith('http'))?.thumbnail_path,
    shortThumbnail: group.find((v) => v.video_type === 'short' && v.thumbnail_path?.startsWith('http'))?.thumbnail_path,
    showGate5: group.some((v) => v.gate5_state === 'awaiting_review'),
    videos: group,
  }))
}

export default async function MediaPage() {
  const supabase = await createClient()
  const { data: videos } = await supabase
    .from('videos')
    .select('*, scripts(youtube_title, long_form_text), niches(name)')
    .or('gate4_state.eq.awaiting_review,gate5_state.eq.awaiting_review,gate6_state.eq.awaiting_review')
    .order('created_at')

  const rows = (videos ?? []) as VideoRow[]
  const groups = groupByScript(rows)

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">Media Review</h1>
      <p className="text-sm text-gray-500 mb-6">Gates 4/5/6 — {groups.length} script(s) awaiting review</p>

      {!groups.length ? (
        <p className="text-gray-500">Queue is empty.</p>
      ) : (
        <div className="space-y-4">
          {groups.map((group) => (
            <ScriptGroupCard key={group.scriptId} group={group} />
          ))}
        </div>
      )}
    </div>
  )
}

function ScriptGroupCard({ group }: { group: ScriptGroup }) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-5">
      <div className="flex gap-5">
        <div className="w-40 h-24 bg-gray-700 rounded overflow-hidden shrink-0 flex items-center justify-center">
          {group.longThumbnail ? (
            <a href={group.longThumbnail} target="_blank" rel="noreferrer" className="w-full h-full block">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={group.longThumbnail} alt="thumbnail" className="object-cover w-full h-full hover:opacity-80 transition-opacity" />
            </a>
          ) : (
            <span className="text-xs text-gray-500">No preview</span>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <p className="font-semibold text-gray-100">{group.title ?? '—'}</p>
          <p className="text-xs text-gray-500 mb-3">{group.nicheName}</p>

          {/* Gate 5 — thumbnail, shared across all formats */}
          {group.showGate5 && (
            <div className="border border-orange-700/50 rounded p-3 bg-orange-900/20 mb-3">
              <p className="text-xs font-semibold text-orange-400 mb-2">Gate 5 — Thumbnail</p>
              <div className="flex gap-3 mb-3">
                {group.longThumbnail && (
                  <div className="flex flex-col items-center gap-1">
                    <span className="text-[10px] text-gray-400 uppercase font-semibold tracking-wide">Long</span>
                    <a href={group.longThumbnail} target="_blank" rel="noreferrer">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={group.longThumbnail} alt="long thumbnail" className="w-32 rounded hover:opacity-80 transition-opacity" />
                    </a>
                  </div>
                )}
                {group.shortThumbnail && (
                  <div className="flex flex-col items-center gap-1">
                    <span className="text-[10px] text-gray-400 uppercase font-semibold tracking-wide">Short</span>
                    <a href={group.shortThumbnail} target="_blank" rel="noreferrer">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={group.shortThumbnail} alt="short thumbnail" className="h-24 rounded hover:opacity-80 transition-opacity" />
                    </a>
                  </div>
                )}
                {!group.longThumbnail && !group.shortThumbnail && (
                  <p className="text-xs text-gray-500">Thumbnails not yet generated</p>
                )}
              </div>
              <div className="flex gap-2 flex-wrap">
                <form action={approveGate5ForScript.bind(null, group.scriptId)}>
                  <button className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700">
                    Approve
                  </button>
                </form>
                <form action={async (fd: FormData) => {
                  'use server'
                  await rejectGate5ForScript(group.scriptId, fd.get('reason') as string || 'Rejected')
                }}>
                  <input name="reason" placeholder="Reason" className="border border-gray-600 bg-gray-700 text-gray-100 placeholder:text-gray-500 rounded px-2 py-1 text-xs w-32" />
                  <button className="bg-gray-700 text-gray-300 text-xs px-3 py-1.5 rounded hover:bg-gray-600 ml-1">
                    Reject
                  </button>
                </form>
                <form action={retryThumbnailForScript.bind(null, group.scriptId)}>
                  <button className="bg-blue-700 text-white text-xs px-3 py-1.5 rounded hover:bg-blue-600">
                    Retry
                  </button>
                </form>
              </div>
            </div>
          )}

          {/* Gates 4 and 6 — per video format */}
          {group.videos.map((v) => {
            const pendingGates = ([4, 6] as const).filter(
              (g) => v[`gate${g}_state`] === 'awaiting_review'
            )
            if (!pendingGates.length) return null
            return (
              <div key={v.id} className="mb-3">
                <p className="text-[10px] text-gray-400 uppercase font-semibold tracking-wide mb-1.5">
                  {v.video_type}
                </p>
                <div className="space-y-2">
                  {pendingGates.map((gate) => (
                    <div key={gate} className="border border-orange-700/50 rounded p-3 bg-orange-900/20">
                      <p className="text-xs font-semibold text-orange-400 mb-2">Gate {gate} — {GATE_LABELS[gate]}</p>

                      {/* Audio player for voiceover review */}
                      {gate === 4 && v.audio_path?.startsWith('http') && (
                        // eslint-disable-next-line jsx-a11y/media-has-caption
                        <audio controls className="w-full mb-2" src={v.audio_path} />
                      )}

                      {/* Video player for final video review */}
                      {gate === 6 && v.video_path?.startsWith('http') && (
                        // eslint-disable-next-line jsx-a11y/media-has-caption
                        <video controls className="w-full rounded mb-2 max-h-48" src={v.video_path} />
                      )}

                      <div className="flex gap-2 flex-wrap">
                        <form action={approveMedia.bind(null, v.id, gate)}>
                          <button className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700">
                            Approve
                          </button>
                        </form>
                        <form action={async (fd: FormData) => {
                          'use server'
                          await rejectMedia(v.id, gate, fd.get('reason') as string || 'Rejected')
                        }}>
                          <input name="reason" placeholder="Reason" className="border border-gray-600 bg-gray-700 text-gray-100 placeholder:text-gray-500 rounded px-2 py-1 text-xs w-32" />
                          <button className="bg-gray-700 text-gray-300 text-xs px-3 py-1.5 rounded hover:bg-gray-600 ml-1">
                            Reject
                          </button>
                        </form>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
