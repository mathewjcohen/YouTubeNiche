export default function Loading() {
  return (
    <div>
      <div className="h-8 w-48 bg-gray-200 rounded animate-pulse mb-2" />
      <div className="h-4 w-96 bg-gray-100 rounded animate-pulse mb-6" />
      <div className="flex gap-4 mb-6">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-white border rounded-lg px-4 py-3 min-w-[90px] h-16 animate-pulse" />
        ))}
      </div>
      <div className="bg-white border rounded-lg overflow-hidden">
        <div className="bg-gray-50 border-b h-10 animate-pulse" />
        {[...Array(8)].map((_, i) => (
          <div key={i} className="h-12 border-b animate-pulse bg-gray-50" style={{ opacity: 1 - i * 0.1 }} />
        ))}
      </div>
    </div>
  )
}
