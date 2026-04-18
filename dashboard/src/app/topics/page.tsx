import { createClient } from '@/lib/supabase/server'
import { approveTopic, rejectTopic } from '@/app/actions/topics'
import type { Topic } from '@/lib/types'

export default async function TopicsPage() {
  const supabase = await createClient()
  const { data: topics } = await supabase
    .from('topics')
    .select('*, niches(name)')
    .eq('gate2_state', 'awaiting_review')
    .order('video_potential_score', { ascending: false })

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">Topic Queue</h1>
      <p className="text-sm text-gray-400 mb-6">Gate 2 — {topics?.length ?? 0} awaiting review</p>

      {!topics?.length ? (
        <p className="text-gray-500">Queue is empty.</p>
      ) : (
        <div className="space-y-4">
          {topics.map((topic) => (
            <TopicCard key={topic.id} topic={topic as Topic & { niches: { name: string } }} />
          ))}
        </div>
      )}
    </div>
  )
}

function TopicCard({ topic }: { topic: Topic & { niches: { name: string } } }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <p className="font-semibold">{topic.title}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            r/{topic.subreddit} · niche: {topic.niches?.name} · score: {topic.video_potential_score?.toFixed(1) ?? '—'}
          </p>
          <p className="text-sm text-gray-600 mt-2 line-clamp-3">{topic.body}</p>
        </div>
        <div className="flex flex-col gap-2 shrink-0">
          <form action={approveTopic.bind(null, topic.id)}>
            <button className="w-full bg-green-600 text-white text-xs px-4 py-1.5 rounded hover:bg-green-700">
              Approve
            </button>
          </form>
          <form
            action={async (fd: FormData) => {
              'use server'
              await rejectTopic(topic.id, fd.get('reason') as string || 'Rejected')
            }}
          >
            <input name="reason" placeholder="Reason (optional)" className="border border-gray-200 rounded px-2 py-1 text-xs w-full mb-1" />
            <button className="w-full bg-gray-200 text-gray-700 text-xs px-4 py-1.5 rounded hover:bg-gray-300">
              Reject
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
