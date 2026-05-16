import { useEffect, useState } from 'react'

/**
 * Re-renders the caller at a regular interval so any "now"-based derivations
 * (live durations, relative timestamps) advance even when the underlying data
 * is unchanged. Pass `null` to disable the ticker.
 */
export function useNow(intervalMs: number | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (intervalMs == null) return
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}
