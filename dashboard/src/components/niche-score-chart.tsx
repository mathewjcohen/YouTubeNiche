'use client'

import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  Legend, ResponsiveContainer, CartesianGrid,
} from 'recharts'

const COLORS = [
  '#60a5fa', '#34d399', '#f59e0b', '#f87171',
  '#a78bfa', '#fb923c', '#38bdf8', '#4ade80',
  '#e879f9', '#facc15', '#94a3b8', '#f472b6',
]

interface HistoryRow {
  niche_name: string
  final_score: number
  recorded_at: string
}

interface Props {
  history: HistoryRow[]
  nicheNames: string[]
}

export function NicheScoreChart({ history, nicheNames }: Props) {
  const dateMap = new Map<string, Record<string, number | string>>()
  for (const row of history) {
    const date = row.recorded_at.slice(0, 10)
    if (!dateMap.has(date)) dateMap.set(date, { date })
    dateMap.get(date)![row.niche_name] = Math.round(row.final_score * 100) / 100
  }
  const data = Array.from(dateMap.values()).sort((a, b) =>
    (a.date as string).localeCompare(b.date as string)
  )

  if (data.length === 0) {
    return <p className="text-sm text-gray-500">No history yet — runs after migration will appear here.</p>
  }

  return (
    <ResponsiveContainer width="100%" height={340}>
      <LineChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 11 }} />
        <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} width={48} />
        <Tooltip
          contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 8 }}
          labelStyle={{ color: '#f9fafb', marginBottom: 4 }}
          itemStyle={{ color: '#d1d5db', fontSize: 12 }}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: '#9ca3af' }} />
        {nicheNames.map((name, i) => (
          <Line
            key={name}
            type="monotone"
            dataKey={name}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
            dot={data.length === 1}
            activeDot={{ r: 4 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
