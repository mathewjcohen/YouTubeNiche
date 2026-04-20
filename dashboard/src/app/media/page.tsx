import { createClient } from '@/lib/supabase/server'
import {
  approveMedia, rejectMedia,
  approveGate5ForScript, rejectGate5ForScript, retryThumbnailForScript,
  retryVoiceover, retryVideoAssembly, returnToScript,
} from '@/app/actions/media'
import { Form, SubmitButton } from '@/components/form'
import { TitleEditor } from './title-editor'
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

function hasActiveGate(v: VideoRow): boolean {
  return (
    v.gate4_state === 'awaiting_review' || v.gate4_state === 'rejected' ||
    v.gate5_state === 'awaiting_review' || v.gate5_state === 'rejected' ||
    v.gate6_state === 'awaiting_review' || v.gate6_state === 'rejected'
  )
}

function deduplicateVideos(videos: VideoRow[]): VideoRow[] {
  // Per (script_id, video_type): prefer the row with an active review gate; break ties by newest.
  const seen = new Map<string, VideoRow>()
  for (const v of videos) {
    const key = `${v.script_id}:${v.video_type}`
    const prev = seen.get(key)
    if (!prev) { seen.set(key, v); continue }
    const vActive = hasActiveGate(v)
    const prevActive = hasActiveGate(prev)
    if (vActive && !prevActive) seen.set(key, v)
    else if (!vActive && prevActive) { /* keep prev */ }
    else if (v.created_at > prev.created_at) seen.set(key, v)
  }
  return Array.from(seen.values())
}

function groupByScript(videos: VideoRow[]): ScriptGroup[] {
  const deduped = deduplicateVideos(videos)
  const map = new Map<string, VideoRow[]>()
  for (const v of deduped) {
    const existing = map.get(v.script_id) ?? []
    map.set(v.script_id, [...existing, v])
  }
  return Array.from(map.values()).map((group) => ({
    scriptId: group[0].script_id,
    title: group[0].scripts?.youtube_title ?? null,
    nicheName: group[0].niches?.name ?? '',
    longThumbnail: group.find((v) => v.video_type === 'long' && v.thumbnail_path?.startsWith('http'))?.thumbnail_path,
    shortThumbnail: group.find((v) => v.video_type === 'short' && v.thumbnail_path?.startsWith('http'))?.thumbnail_path,
    showGate5: group.some((v) => v.gate5_state === 'awaiting_review' || v.gate5_state === 'rejected'),
    videos: group,
  }))
}

export default async function MediaPage() {
  const supabase = await createClient()

  // Find which scripts have at least one video needing review
  const { data: needsReview } = await supabase
    .from('videos')
    .select('script_id')
    .or(
      'gate4_state.in.(awaiting_review,rejected),' +
      'gate5_state.in.(awaiting_review,rejected),' +
      'gate6_state.in.(awaiting_review,rejected)'
    )

  const scriptIds = [...new Set((needsReview ?? []).map((v) => v.script_id))]

  // Fetch ALL video rows for those scripts so groups are always complete
  // (e.g. thumbnail_path lives on the long row even when only the short needs review)
  const rows: VideoRow[] = []
  if (scriptIds.length > 0) {
    const { data: videos } = await supabase
      .from('videos')
      .select('*, scripts(youtube_title, long_form_text), niches(name)')
      .in('script_id', scriptIds)
      .order('created_at')
    rows.push(...((videos ?? []) as VideoRow[]))
  }

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

function GateBadge({ isRejected, label }: { isRejected: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <p className={`text-xs font-semibold ${isRejected ? 'text-red-400' : 'text-orange-400'}`}>{label}</p>
      {isRejected && (
        <span className="text-xs text-red-400 bg-red-900/40 px-1.5 py-0.5 rounded">Rejected</span>
      )}
    </div>
  )
}

function RejectionReason({ reason }: { reason: string | null | undefined }) {
  if (!reason) return null
  return <p className="text-xs text-red-300 mb-2 italic">&ldquo;{reason}&rdquo;</p>
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
          <TitleEditor scriptId={group.scriptId} initialTitle={group.title} />
          <p className="text-xs text-gray-500 mb-3">{group.nicheName}</p>

          {/* Gate 5 — thumbnail, shared across all formats */}
          {group.showGate5 && (() => {
            const gate5Video = group.videos.find(v => v.gate5_state === 'awaiting_review' || v.gate5_state === 'rejected')
            const isRejected = gate5Video?.gate5_state === 'rejected'
            const reason = gate5Video?.gate5_rejection_reason
            return (
              <div className={`border rounded p-3 mb-3 ${isRejected ? 'border-red-700/50 bg-red-900/20' : 'border-orange-700/50 bg-orange-900/20'}`}>
                <GateBadge isRejected={isRejected ?? false} label="Gate 5 — Thumbnail" />
                <RejectionReason reason={reason} />
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
                  {!isRejected && (
                    <>
                      <Form action={approveGate5ForScript.bind(null, group.scriptId)} successMessage="Thumbnail approved">
                        <SubmitButton className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700">
                          Approve
                        </SubmitButton>
                      </Form>
                      <Form
                        action={async (fd: FormData) => {
                          'use server'
                          await rejectGate5ForScript(group.scriptId, fd.get('reason') as string || 'Rejected')
                        }}
                        successMessage="Thumbnail rejected"
                      >
                        <input name="reason" placeholder="Reason" className="border border-gray-600 bg-gray-700 text-gray-100 placeholder:text-gray-500 rounded px-2 py-1 text-xs w-32" />
                        <SubmitButton className="bg-gray-700 text-gray-300 text-xs px-3 py-1.5 rounded hover:bg-gray-600 ml-1">
                          Reject
                        </SubmitButton>
                      </Form>
                    </>
                  )}
                  <Form action={retryThumbnailForScript.bind(null, group.scriptId)} successMessage="Thumbnail retry queued">
                    <SubmitButton className="bg-blue-700 text-white text-xs px-3 py-1.5 rounded hover:bg-blue-600">
                      Retry
                    </SubmitButton>
                  </Form>
                </div>
              </div>
            )
          })()}

          {/* Gates 4 and 6 — per video format */}
          {group.videos.map((v) => {
            const activeGates = ([4, 6] as const).filter((g) => {
              const state = v[`gate${g}_state`]
              if (state !== 'awaiting_review' && state !== 'rejected') return false
              // Gate 6 only shown when gate 4 and gate 5 are both approved
              if (g === 6 && (v.gate4_state !== 'approved' || v.gate5_state !== 'approved')) return false
              return true
            })
            if (!activeGates.length) return null
            return (
              <div key={v.id} className="mb-3">
                <p className="text-[10px] text-gray-400 uppercase font-semibold tracking-wide mb-1.5">
                  {v.video_type}
                </p>
                <div className="space-y-2">
                  {activeGates.map((gate) => {
                    const state = v[`gate${gate}_state`]
                    const reason = v[`gate${gate}_rejection_reason`]
                    const isRejected = state === 'rejected'
                    return (
                      <div key={gate} className={`border rounded p-3 ${isRejected ? 'border-red-700/50 bg-red-900/20' : 'border-orange-700/50 bg-orange-900/20'}`}>
                        <GateBadge isRejected={isRejected} label={`Gate ${gate} — ${GATE_LABELS[gate]}`} />
                        <RejectionReason reason={reason} />

                        {gate === 4 && v.audio_path?.startsWith('http') && (
                          // eslint-disable-next-line jsx-a11y/media-has-caption
                          <audio controls className="w-full mb-2" src={v.audio_path} />
                        )}

                        {gate === 6 && v.video_path?.startsWith('http') && (
                          // eslint-disable-next-line jsx-a11y/media-has-caption
                          <video controls className="w-full rounded mb-2 max-h-48" src={v.video_path} />
                        )}

                        <div className="flex gap-2 flex-wrap">
                          {!isRejected && (
                            <>
                              <Form action={approveMedia.bind(null, v.id, gate)} successMessage={`Gate ${gate} approved`}>
                                <SubmitButton className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700">
                                  Approve
                                </SubmitButton>
                              </Form>
                              <Form
                                action={async (fd: FormData) => {
                                  'use server'
                                  await rejectMedia(v.id, gate, fd.get('reason') as string || 'Rejected')
                                }}
                                successMessage={`Gate ${gate} rejected`}
                              >
                                <input name="reason" placeholder="Reason" className="border border-gray-600 bg-gray-700 text-gray-100 placeholder:text-gray-500 rounded px-2 py-1 text-xs w-32" />
                                <SubmitButton className="bg-gray-700 text-gray-300 text-xs px-3 py-1.5 rounded hover:bg-gray-600 ml-1">
                                  Reject
                                </SubmitButton>
                              </Form>
                            </>
                          )}
                          {gate === 4 ? (
                            <div className="flex gap-2 flex-wrap">
                              <Form action={retryVoiceover.bind(null, v.id)} successMessage="Voiceover retry queued">
                                <SubmitButton className="bg-blue-700 text-white text-xs px-3 py-1.5 rounded hover:bg-blue-600">
                                  Retry Voiceover
                                </SubmitButton>
                              </Form>
                              <Form action={returnToScript.bind(null, v.id)} successMessage="Returned to script queue">
                                <SubmitButton className="bg-yellow-700 text-white text-xs px-3 py-1.5 rounded hover:bg-yellow-600">
                                  Return to Script
                                </SubmitButton>
                              </Form>
                            </div>
                          ) : (
                            <>
                              <Form action={retryVoiceover.bind(null, v.id)} successMessage="Voiceover retry queued">
                                <SubmitButton className="bg-blue-700 text-white text-xs px-3 py-1.5 rounded hover:bg-blue-600">
                                  Retry Voiceover
                                </SubmitButton>
                              </Form>
                              <Form action={retryVideoAssembly.bind(null, v.id)} successMessage="Assembly retry queued">
                                <SubmitButton className="bg-blue-700 text-white text-xs px-3 py-1.5 rounded hover:bg-blue-600">
                                  Retry Assembly
                                </SubmitButton>
                              </Form>
                            </>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
