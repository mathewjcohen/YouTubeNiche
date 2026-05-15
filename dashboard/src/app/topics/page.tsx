import { createClient } from '@/lib/supabase/server'
import { approveTopic, rejectTopic, approveTopBatch } from '@/app/actions/topics'
import { setTopicRunnerEnabled } from '@/app/actions/settings'
import { Form, SubmitButton } from '@/components/form'
import type { Topic } from '@/lib/types'

export default async function TopicsPage() {
  const supabase = await createClient()
  const [{ data: topics }, { data: appSettings }] = await Promise.all([
    supabase.from('topics').select('*').eq('gate2_state', 'awaiting_review').order('claude_score', { ascending: false }).order('id', { ascending: true }),
    supabase.from('app_settings').select('key, value').eq('key', 'topic_runner_enabled'),
  ])

  const rows = (topics ?? []) as Topic[]
  const topicRunnerEnabled = ((appSettings as { key: string; value: string }[] | null)?.find(s => s.key === 'topic_runner_enabled')?.value ?? 'true') === 'true'

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">Topic Queue</h1>
          <span className={`text-xs font-medium px-2 py-0.5 rounded ${topicRunnerEnabled ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
            {topicRunnerEnabled ? 'Running' : 'Paused'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Form
            action={setTopicRunnerEnabled}
            successMessage={topicRunnerEnabled ? 'Topic runner paused' : 'Topic runner resumed'}
          >
            <input type="hidden" name="topic_runner_enabled" value={topicRunnerEnabled ? 'false' : 'true'} />
            <SubmitButton
              className={`text-xs px-3 py-1.5 rounded ${topicRunnerEnabled ? 'bg-red-700 hover:bg-red-600 text-white' : 'bg-green-700 hover:bg-green-600 text-white'}`}
            >
              {topicRunnerEnabled ? 'Pause Topic Runner' : 'Resume Topic Runner'}
            </SubmitButton>
          </Form>
          {rows.length > 0 && (
            <Form action={approveTopBatch} successMessage="Batch approved" className="flex items-center gap-2">
              <span className="text-xs text-gray-500">Approve top</span>
              <input
                name="count"
                type="number"
                min={1}
                max={20}
                defaultValue={3}
                className="w-14 border border-gray-600 bg-gray-700 text-gray-100 rounded px-2 py-1 text-xs text-center"
              />
              <SubmitButton className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700 whitespace-nowrap">
                Approve
              </SubmitButton>
            </Form>
          )}
        </div>
      </div>
      <p className="text-sm text-gray-500 mb-6">Gate 2 — {rows.length} awaiting review</p>

      {!rows.length ? (
        <p className="text-gray-500">Queue is empty.</p>
      ) : (
        <div className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden divide-y divide-gray-700">
          {rows.map((topic) => (
            <TopicCard key={topic.id} topic={topic} />
          ))}
        </div>
      )}
    </div>
  )
}

function TopicCard({ topic }: { topic: Topic }) {
  return (
    <div className="px-5 py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <p className="font-semibold text-gray-100">{topic.title}</p>
          <p className="text-xs text-gray-500 mt-0.5">score: {topic.claude_score?.toFixed(1) ?? '—'}</p>
          <p className="text-sm text-gray-400 mt-2 line-clamp-3">{topic.body}</p>
        </div>
        <div className="flex flex-col gap-2 shrink-0">
          <Form action={approveTopic.bind(null, topic.id)} successMessage="Topic approved">
            <SubmitButton className="w-full bg-green-600 text-white text-xs px-4 py-1.5 rounded hover:bg-green-700">
              Approve
            </SubmitButton>
          </Form>
          <Form
            action={async (fd: FormData) => {
              'use server'
              await rejectTopic(topic.id, fd.get('reason') as string || 'Rejected')
            }}
            successMessage="Topic rejected"
          >
            <input name="reason" placeholder="Reason (optional)" className="border border-gray-600 bg-gray-700 text-gray-100 placeholder:text-gray-500 rounded px-2 py-1 text-xs w-full mb-1" />
            <SubmitButton className="w-full bg-gray-700 text-gray-300 text-xs px-4 py-1.5 rounded hover:bg-gray-600">
              Reject
            </SubmitButton>
          </Form>
        </div>
      </div>
    </div>
  )
}
