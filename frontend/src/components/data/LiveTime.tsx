import { formatDuration, formatRelative } from '#/lib/format'
import { useNow } from '#/lib/useNow'

export function LiveDuration({
  startedAt,
  completedAt,
}: {
  startedAt?: string | null
  completedAt?: string | null
}) {
  const running = Boolean(startedAt && !completedAt)
  const now = useNow(running ? 1000 : null)
  if (!startedAt) return <>–</>
  if (completedAt) {
    return (
      <>
        {formatDuration(
          new Date(completedAt).getTime() - new Date(startedAt).getTime(),
        )}
      </>
    )
  }
  return <>{formatDuration(now - new Date(startedAt).getTime())}</>
}

export function LiveRelative({
  value,
  intervalMs = 15_000,
}: {
  value?: string | Date | null
  intervalMs?: number
}) {
  useNow(value ? intervalMs : null)
  return <>{formatRelative(value)}</>
}
