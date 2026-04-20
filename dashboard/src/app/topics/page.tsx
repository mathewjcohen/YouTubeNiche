import { createClient } from '@/lib/supabase/server'
import { approveTopic, rejectTopic, approveTopBatch, approveTopBatchPerNiche } from '@/app/actions/topics'
import { Form, SubmitButton } from '@/components/form'
import { Collapsible } from '@/components/collapsible'
import type { Topic } from '@/lib/types'

type TopicRow = Topic & { niches: { name: string } }

type NicheGroup = {
  nicheId: string
  nicheName: string
  topics: TopicRow[]
}

function groupByNiche(topics: TopicRow[]): NicheGroup[] {
  const map = new Map<string, NicheGroup>()
  for (const topic of topics) {
    const id = topic.niche_id
    const name = topic.niches?.name ?? 'Unknown'
    if (!map.has(id)) map.set(id, { nicheId: id, nicheName: name, topics: [] })
    map.get(id)!.topics.push(topic)
  }
  return Array.from(map.values())
}

export default async function TopicsPage() {
  const supabase = await createClient()
  const { data: topics } = await supabase
    .from('topics')
    .select('*, niches(name)')
    .eq('gate2_state', 'awaiting_review')
    .order('claude_score', { ascending: false })

  const rows = (topics ?? []) as TopicRow[]
  const groups = groupByNiche(rows)

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-bold">Topic Queue</h1>
        {rows.length > 0 && (
          <div className="flex flex-col gap-1.5 items-end">
            <Form action={approveTopBatch} successMessage="Batch approved" className="flex items-center gap-2">
              <span className="text-xs text-gray-500 w-24 text-right">Top across all</span>
              <input
                name="count"
                type="number"
                min={1}
                max={20}
                defaultValue={3}
                className="w-14 border border-gray-600 bg-gray-700 text-gray-100 rounded px-2 py-1 text-xs text-center"
              />
              <SubmitButton className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700 whitespace-nowrap w-24">
                Approve
              </SubmitButton>
            </Form>
            <Form action={approveTopBatchPerNiche} successMessage="Per-niche batch approved" className="flex items-center gap-2">
              <span className="text-xs text-gray-500 w-24 text-right">Top per niche</span>
              <input
                name="count"
                type="number"
                min={1}
                max={20}
                defaultValue={3}
                className="w-14 border border-gray-600 bg-gray-700 text-gray-100 rounded px-2 py-1 text-xs text-center"
              />
              <SubmitButton className="bg-green-600 text-white text-xs px-3 py-1.5 rounded hover:bg-green-700 whitespace-nowrap w-24">
                Approve
              </SubmitButton>
            </Form>
          </div>
        )}
      </div>
      <p className="text-sm text-gray-500 mb-6">Gate 2 — {rows.length} awaiting review</p>

      {!rows.length ? (
        <p className="text-gray-500">Queue is empty.</p>
      ) : (
        <div className="space-y-3">
          {groups.map((group) => (
            <Collapsible
              key={group.nicheId}
              defaultOpen
              className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden"
              titleClassName="px-5 py-3.5"
              title={
                <div className="flex items-center gap-3">
                  <span className="font-semibold text-gray-100">{group.nicheName}</span>
                  <span className="text-xs bg-gray-700 text-gray-400 px-2 py-0.5 rounded-full">
                    {group.topics.length}
                  </span>
                </div>
              }
            >
              <div className="divide-y divide-gray-700 border-t border-gray-700">
                {group.topics.map((topic) => (
                  <TopicCard key={topic.id} topic={topic} />
                ))}
              </div>
            </Collapsible>
          ))}
        </div>
      )}
    </div>
  )
}

function TopicCard({ topic }: { topic: TopicRow }) {
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
