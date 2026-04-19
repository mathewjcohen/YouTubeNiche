'use client'

export function ScoreTooltip({ score }: { score: number }) {
  return (
    <div className="relative group">
      <span className="text-sm text-gray-400 cursor-help border-b border-dashed border-gray-600">
        Score: {score.toFixed(2)}
      </span>
      <div className="hidden group-hover:block absolute right-0 top-full mt-2 z-20 w-76 bg-gray-900 border border-gray-600 rounded-lg p-3.5 text-xs text-gray-300 shadow-2xl">
        <p className="font-semibold text-gray-100 mb-1">How this score is calculated</p>
        <p className="font-mono text-[10px] text-gray-500 mb-3">RPM × Trend × Audience ÷ Competition</p>
        <div className="space-y-2">
          <div>
            <span className="text-gray-200 font-medium">RPM </span>
            <span className="text-gray-400">— estimated ad revenue per 1,000 views for this category. Higher-value categories (legal, finance) earn more per view.</span>
          </div>
          <div>
            <span className="text-gray-200 font-medium">Trend </span>
            <span className="text-gray-400">— recent 4-week Google Trends vs. 12-month average. Above 1.0 means the topic is growing right now.</span>
          </div>
          <div>
            <span className="text-gray-200 font-medium">Audience </span>
            <span className="text-gray-400">— Reddit engagement score (1–10). Higher means a large, active audience already exists.</span>
          </div>
          <div>
            <span className="text-gray-200 font-medium">Competition </span>
            <span className="text-gray-400">— average views of top 10 YouTube videos (1–10). Lower is better — easier to rank in a less saturated space.</span>
          </div>
        </div>
        <p className="mt-3 pt-2.5 border-t border-gray-700 text-gray-500">
          Higher score = better opportunity. There is no fixed ceiling.
        </p>
      </div>
    </div>
  )
}
