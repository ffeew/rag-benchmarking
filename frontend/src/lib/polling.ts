const TERMINAL_STATUSES = new Set(['completed', 'failed', 'skipped', 'cancelled'])

export function isTerminalJobStatus(status?: string | null): boolean {
  return status ? TERMINAL_STATUSES.has(status) : false
}

/* Helpers to compute the next refetch interval based on payload.
 * They are intentionally simple (operate on payload, not on the full
 * TanStack Query object) so they can be reused inside an inline
 * `refetchInterval` callback at the call site. */

export function nextJobInterval(
  status: string | null | undefined,
  intervalMs: number,
): number | false {
  return isTerminalJobStatus(status) ? false : intervalMs
}

export function nextJobsListInterval(
  jobs: ReadonlyArray<{ status?: string | null }> | undefined,
  intervalMs: number,
): number | false {
  if (!jobs || jobs.length === 0) return intervalMs
  return jobs.some((job) => !isTerminalJobStatus(job.status)) ? intervalMs : false
}
