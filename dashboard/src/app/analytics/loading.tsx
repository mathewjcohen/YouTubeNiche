export default function AnalyticsLoading() {
  return (
    <div>
      <div className="h-8 w-32 bg-gray-700 rounded animate-pulse mb-6" />
      <div className="grid grid-cols-1 gap-6">
        {[0, 1, 2].map((i) => (
          <div key={i} className="bg-gray-800 border border-gray-700 rounded-lg p-5">
            <div className="flex items-center gap-3 mb-5">
              <div className="h-5 w-16 bg-gray-700 rounded-full animate-pulse" />
              <div className="h-5 w-40 bg-gray-700 rounded animate-pulse" />
              <div className="h-4 w-20 bg-gray-700 rounded animate-pulse" />
            </div>
            <div className="grid grid-cols-4 gap-3 mb-3">
              {[0, 1, 2, 3, 4, 5, 6, 7].map((j) => (
                <div key={j} className="bg-gray-900/50 rounded-lg p-3 text-center">
                  <div className="h-3 w-16 bg-gray-700 rounded animate-pulse mx-auto mb-2" />
                  <div className="h-6 w-12 bg-gray-600 rounded animate-pulse mx-auto" />
                </div>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[0, 1].map((j) => (
                <div key={j} className="bg-gray-900/50 rounded-lg p-3 h-16 animate-pulse" />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
