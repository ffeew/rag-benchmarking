import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Activity, Brush, RotateCcw, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Select } from '#/components/ui/input'
import { Pagination } from '#/components/ui/pagination'
import { Progress } from '#/components/ui/progress'
import { Skeleton } from '#/components/ui/skeleton'
import { StatusDot } from '#/components/ui/status-dot'
import { Table, TBody, TD, TH, THead, TR } from '#/components/ui/table'
import { EmptyState } from '#/components/data/EmptyState'
import { ErrorState } from '#/components/data/ErrorState'
import { LiveDuration, LiveRelative } from '#/components/data/LiveTime'
import { api } from '#/lib/api'
import type { Job } from '#/lib/api'
import { truncate, truncateId } from '#/lib/format'
import { isTerminalJobStatus, nextJobsListInterval } from '#/lib/polling'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { toast, toastApiError } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/jobs/')({ component: JobsList })

const RETRYABLE = new Set(['failed', 'completed_with_errors', 'cancelled'])
const CANCELLABLE = new Set(['queued', 'running'])

// Curated lists — paginated data only sees the current page, so we can no
// longer derive dropdown options from the visible rows.
const JOB_TYPES = ['ingestion', 'evaluation'] as const
const JOB_STATUSES = [
  'queued',
  'running',
  'completed',
  'completed_with_errors',
  'failed',
  'cancelled',
  'skipped',
] as const

function JobsList() {
  const { token, isAuthed } = useToken()
  const queryClient = useQueryClient()
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    setOffset(0)
  }, [typeFilter, statusFilter, limit])

  const jobsQuery = useQuery({
    queryKey: qk.jobs.list({
      jobType: typeFilter || undefined,
      status: statusFilter || undefined,
      limit,
      offset,
    }),
    queryFn: () =>
      api.jobs(token, {
        job_type: typeFilter || undefined,
        status: statusFilter || undefined,
        limit,
        offset,
      }),
    enabled: isAuthed,
    placeholderData: keepPreviousData,
    refetchInterval: (q) => nextJobsListInterval(q.state.data?.items, 3500),
  })

  const items = jobsQuery.data?.items ?? []
  const total = jobsQuery.data?.total ?? 0

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: qk.jobs.all() })

  const sweepMutation = useMutation({
    mutationFn: () => api.sweepJobs(token),
    onSuccess: ({ redispatched, exhausted, reaped }) => {
      if (redispatched === 0 && exhausted === 0 && reaped === 0) {
        toast.success('Sweep complete', 'No stuck jobs found.')
      } else {
        toast.success(
          'Sweep complete',
          `Redispatched ${redispatched} · reaped ${reaped} · exhausted ${exhausted}.`,
        )
      }
      invalidate()
    },
    onError: (err) => toastApiError(err, 'Failed to trigger sweep'),
  })

  const retryMutation = useMutation({
    mutationFn: (id: string) => api.retryJob(token, id),
    onSuccess: (job) => {
      toast.success('Retry queued', truncateId(job.id))
      invalidate()
    },
    onError: (err) => toastApiError(err, 'Retry failed'),
  })

  const cancelMutation = useMutation({
    mutationFn: (id: string) => api.cancelJob(token, id),
    onSuccess: (job) => {
      toast.success('Cancelled', truncateId(job.id))
      invalidate()
    },
    onError: (err) => toastApiError(err, 'Cancel failed'),
  })

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6 grid gap-5">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mono-label text-[var(--ink-muted)]">RUNTIME</div>
          <h1 className="mt-1 text-[24px] leading-tight font-semibold tracking-tight">
            Jobs
          </h1>
          <p className="mt-1 text-[13px] text-[var(--ink-dim)]">
            Live monitor for ingestion and evaluation workers. The sweeper
            recovers stranded rows every 60 seconds — use the button below for
            an immediate pass.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3 text-[11.5px]">
          <span className="inline-flex items-center gap-1.5">
            <span className="font-mono numeric text-[var(--ink-dim)]">
              {total}
            </span>
            <span className="mono-label">TOTAL</span>
          </span>
          <Button
            size="sm"
            onClick={() => sweepMutation.mutate()}
            disabled={sweepMutation.isPending}
            leading={<Brush className="h-3.5 w-3.5" />}
          >
            {sweepMutation.isPending ? 'Sweeping…' : 'Sweep stuck jobs'}
          </Button>
        </div>
      </header>

      <Card>
        <CardHeader
          title={
            <span>
              ALL JOBS{' '}
              <span className="font-mono numeric text-[var(--ink-muted)]">
                · {items.length}/{total}
              </span>
            </span>
          }
          actions={
            <div className="flex items-center gap-2">
              <Select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="h-7 w-[140px] text-[12px]"
              >
                <option value="">All types</option>
                {JOB_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
              <Select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="h-7 w-[140px] text-[12px]"
              >
                <option value="">All statuses</option>
                {JOB_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </div>
          }
        />
        <CardBody padded={false}>
          {jobsQuery.isLoading ? (
            <div className="p-4 grid gap-1.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : jobsQuery.isError ? (
            <ErrorState
              error={jobsQuery.error}
              onRetry={() => jobsQuery.refetch()}
            />
          ) : items.length === 0 ? (
            <EmptyState
              icon={Activity}
              title="No jobs"
              description={
                total === 0
                  ? 'Ingestion or evaluation jobs will appear here once started.'
                  : 'No jobs match your filters.'
              }
            />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH className="w-8"></TH>
                  <TH>TYPE</TH>
                  <TH>STATUS</TH>
                  <TH>PROGRESS</TH>
                  <TH>STEP</TH>
                  <TH>RETRIES</TH>
                  <TH>STARTED</TH>
                  <TH>DURATION</TH>
                  <TH className="text-right">ACTIONS</TH>
                </tr>
              </THead>
              <TBody>
                {items.map((j) => (
                  <JobRow
                    key={j.id}
                    job={j}
                    onRetry={() => retryMutation.mutate(j.id)}
                    onCancel={() => cancelMutation.mutate(j.id)}
                    retrying={
                      retryMutation.isPending &&
                      retryMutation.variables === j.id
                    }
                    cancelling={
                      cancelMutation.isPending &&
                      cancelMutation.variables === j.id
                    }
                  />
                ))}
              </TBody>
            </Table>
          )}
          <Pagination
            total={total}
            limit={limit}
            offset={offset}
            onChange={({ limit: nextLimit, offset: nextOffset }) => {
              setLimit(nextLimit)
              setOffset(nextOffset)
            }}
          />
        </CardBody>
      </Card>
    </div>
  )
}

function JobRow({
  job,
  onRetry,
  onCancel,
  retrying,
  cancelling,
}: {
  job: Job
  onRetry: () => void
  onCancel: () => void
  retrying: boolean
  cancelling: boolean
}) {
  const terminal = isTerminalJobStatus(job.status)
  return (
    <TR interactive>
      <TD>
        <StatusDot status={job.status} />
      </TD>
      <TD>
        <Link
          {...paths.job(job.id)}
          className="font-mono text-[12px] hover:underline"
        >
          {job.job_type}
        </Link>
        <div className="font-mono text-[10.5px] text-[var(--ink-muted)]">
          {truncateId(job.id)}
        </div>
      </TD>
      <TD>
        <Badge tone={toneForStatus(job.status)} size="sm">
          {job.status}
        </Badge>
      </TD>
      <TD className="min-w-[160px]">
        <Progress value={job.progress} showLabel />
      </TD>
      <TD className="max-w-[260px] truncate text-[var(--ink-dim)]">
        {job.error ? (
          <span className="font-mono text-[var(--bad)]">
            {truncate(job.error, 60)}
          </span>
        ) : (
          (job.current_step ?? '–')
        )}
      </TD>
      <TD className="font-mono text-[11px] text-[var(--ink-muted)]">
        {job.retry_count}
      </TD>
      <TD className="font-mono text-[11px] text-[var(--ink-muted)]">
        <LiveRelative
          value={job.started_at ?? job.created_at}
          intervalMs={terminal ? 30_000 : 1000}
        />
      </TD>
      <TD className="font-mono text-[11px] text-[var(--ink-muted)]">
        <LiveDuration
          startedAt={job.started_at}
          completedAt={job.completed_at}
        />
      </TD>
      <TD className="text-right">
        <div className="inline-flex gap-1">
          {RETRYABLE.has(job.status) && (
            <Button
              size="xs"
              variant="ghost"
              onClick={onRetry}
              disabled={retrying}
              leading={<RotateCcw className="h-3 w-3" />}
            >
              {retrying ? '…' : 'Retry'}
            </Button>
          )}
          {CANCELLABLE.has(job.status) && (
            <Button
              size="xs"
              variant="ghost"
              onClick={onCancel}
              disabled={cancelling}
              leading={<X className="h-3 w-3" />}
            >
              {cancelling ? '…' : 'Cancel'}
            </Button>
          )}
        </div>
      </TD>
    </TR>
  )
}
