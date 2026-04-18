export function GateBadge({ count }: { count: number }) {
  if (count === 0) return null
  return (
    <span className="ml-auto inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-500 text-white text-xs font-bold">
      {count > 9 ? '9+' : count}
    </span>
  )
}
