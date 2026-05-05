'use client'

import { useState, useMemo } from 'react'
import type { VideoRecord } from '@/lib/types'

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(0)}%`
}

function fmtDur(sec: number | null | undefined): string {
  if (sec == null || sec === 0) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function fmtNum(v: number | null | undefined): string {
  if (v == null) return '—'
  return v.toLocaleString()
}

type SortKey = 'views' | 'avg_view_pct' | 'likes' | 'retention_50pct'

export function VideoTable({ videos, nicheNames }: { videos: VideoRecord[]; nicheNames: string[] }) {
  const [nicheFilter, setNicheFilter] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [sortKey, setSortKey] = useState<SortKey>('views')
  const [sortDesc, setSortDesc] = useState(true)

  const filtered = useMemo(() => {
    let rows = videos
    if (nicheFilter !== 'all') rows = rows.filter((v) => v.niche_name === nicheFilter)
    if (typeFilter !== 'all') rows = rows.filter((v) => v.video_type === typeFilter)
    return [...rows].sort((a, b) => {
      const av = a[sortKey] ?? -1
      const bv = b[sortKey] ?? -1
      return sortDesc ? (bv as number) - (av as number) : (av as number) - (bv as number)
    })
  }, [videos, nicheFilter, typeFilter, sortKey, sortDesc])

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDesc((d) => !d)
    } else {
      setSortKey(key)
      setSortDesc(true)
    }
  }

  function SortHeader({ label, col }: { label: string; col: SortKey }) {
    const active = sortKey === col
    return (
      <th
        className="text-right pb-2 font-medium cursor-pointer select-none hover:text-gray-300 transition-colors"
        onClick={() => handleSort(col)}
      >
        {label}
        {active && <span className="ml-1 text-gray-400">{sortDesc ? '↓' : '↑'}</span>}
      </th>
    )
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex items-center gap-3 mb-3 flex-wrap">
        <select
          value={nicheFilter}
          onChange={(e) => setNicheFilter(e.target.value)}
          className="bg-gray-800 border border-gray-600 text-gray-300 text-xs rounded px-2 py-1.5 cursor-pointer focus:outline-none focus:border-gray-500"
        >
          <option value="all">All niches</option>
          {nicheNames.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>

        <div className="flex rounded overflow-hidden border border-gray-600">
          {(['all', 'long', 'short'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-3 py-1.5 text-xs cursor-pointer transition-colors ${
                typeFilter === t
                  ? 'bg-gray-600 text-gray-100'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {t === 'all' ? 'All' : t === 'long' ? 'Long' : 'Shorts'}
            </button>
          ))}
        </div>

        <span className="text-xs text-gray-600 ml-auto">{filtered.length} video{filtered.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-700">
              <th className="text-left pb-2 font-medium">Title</th>
              <th className="text-left pb-2 font-medium">Niche</th>
              <th className="text-left pb-2 font-medium">Type</th>
              <th className="text-right pb-2 font-medium">Duration</th>
              <SortHeader label="Views" col="views" />
              <SortHeader label="Watch %" col="avg_view_pct" />
              <SortHeader label="Likes" col="likes" />
              <SortHeader label="50% Drop" col="retention_50pct" />
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-6 text-center text-gray-600">No videos match the current filters.</td>
              </tr>
            ) : (
              filtered.map((v) => {
                const watchThreshold = v.video_type === 'long' ? 0.35 : 0.5
                const watchGood = (v.avg_view_pct ?? 0) >= watchThreshold
                return (
                  <tr key={v.youtube_video_id} className="border-b border-gray-700/50 hover:bg-gray-700/20">
                    <td className="py-1.5 max-w-[200px]">
                      <a
                        href={`https://youtube.com/watch?v=${v.youtube_video_id}`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-gray-200 hover:text-blue-400 truncate block cursor-pointer transition-colors"
                        title={v.title}
                      >
                        {v.title}
                      </a>
                    </td>
                    <td className="py-1.5 text-gray-400 max-w-[120px] truncate">{v.niche_name}</td>
                    <td className="py-1.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                          v.video_type === 'long'
                            ? 'bg-blue-900/40 text-blue-300'
                            : 'bg-purple-900/40 text-purple-300'
                        }`}
                      >
                        {v.video_type === 'long' ? 'Long' : 'Short'}
                      </span>
                    </td>
                    <td className="py-1.5 text-right text-gray-400">{fmtDur(v.duration_sec)}</td>
                    <td className="py-1.5 text-right text-gray-200">{fmtNum(v.views)}</td>
                    <td className={`py-1.5 text-right font-medium ${watchGood ? 'text-green-400' : 'text-gray-200'}`}>
                      {fmtPct(v.avg_view_pct)}
                    </td>
                    <td className="py-1.5 text-right text-gray-200">{fmtNum(v.likes)}</td>
                    <td className="py-1.5 text-right">
                      {v.retention_50pct != null ? (
                        <span className={`font-medium ${v.retention_50pct < 0.3 ? 'text-red-400' : v.retention_50pct < 0.6 ? 'text-yellow-400' : 'text-gray-300'}`}>
                          {fmtPct(v.retention_50pct)}
                        </span>
                      ) : (
                        <span className="text-gray-600">—</span>
                      )}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
