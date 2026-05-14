import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, ChevronDown, RotateCw, X } from 'lucide-react'
import { useState } from 'react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Progress } from '#/components/ui/progress'
import { Skeleton } from '#/components/ui/skeleton'
import { StatusDot } from '#/components/ui/status-dot'
import { ErrorState } from '#/components/data/ErrorState'
import { KeyValueGrid } from '#/components/data/KeyValueGrid'
import type { KVRow } from '#/components/data/KeyValueGrid'
import { api } from '#/lib/api'
import { formatDateTime, formatDuration } from '#/lib/format'
import { isTerminalJobStatus, nextJobInterval } from '#/lib/polling'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { toast, toastApiError } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/jobs/$jobId')({ component: JobDetail })

function JobDetail() {
  const { jobId } = Route.useParams()
  const { token, isAuthed } = useToken()
  const queryClient = useQueryClient()
  const [showMeta, setShowMeta] = useState(false)

  const jobQuery = useQuery({
    queryKey: qk.jobs.detail(jobId),
    queryFn: () => api.job(token, jobId),
    enabled: isAuthed,
    refetchInterval: (q) => nextJobInterval(q.state.data?.status, 2500),
  })

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelJob(token, jobId),
    onSuccess: () => {
      toast.success('Cancel requested')
      void queryClient.invalidateQueries({ queryKey: qk.jobs.all() })
    },
    onError: (err) => toastApiError(err, 'Cancel failed'),
  })

  const retryMutation = useMutation({
    mutationFn: () => api.retryJob(token, jobId),
    onSuccess: () => {
      toast.success('Retry queued')
      void queryClient.invalidateQueries({ queryKey: qk.jobs.all() })
    },
    onError: (err) => toastApiError(err, 'Retry failed'),
  })

  if (jobQuery.isLoading) {
    return (
      <div className="p-6 grid gap-3">
        <Skeleton className="h-6 w-72" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  if (jobQuery.isError || !jobQuery.data) {
    return (
      <ErrorState
        title="Job not found"
        error={jobQuery.error}
        onRetry={() => jobQuery.refetch()}
      />
    )
  }

  const job = jobQuery.data
  const terminal = isTerminalJobStatus(job.status)
  const duration =
    job.started_at && job.completed_at
      ? new Date(job.completed_at).getTime() -
        new Date(job.started_at).getTime()
      : job.started_at
        ? Date.now() - new Date(job.started_at).getTime()
        : null

  const rows: Array<KVRow> = [
    { key: 'job id', value: job.id, mono: true, copyable: true },
    { key: 'type', value: job.job_type, mono: true },
    { key: 'status', value: job.status, mono: true },
    { key: 'progress', value: `${Math.round(job.progress)}%`, mono: true },
    job.current_step
      ? { key: 'current step', value: job.current_step, mono: true }
      : null,
    job.dataset_id
      ? {
          key: 'dataset',
          value: job.dataset_id.slice(0, 12),
          mono: true,
        }
      : null,
    job.document_id
      ? { key: 'document', value: job.document_id, mono: true, copyable: true }
      : null,
    job.eval_run_id
      ? { key: 'eval run', value: job.eval_run_id, mono: true, copyable: true }
      : null,
    job.started_at
      ? { key: 'started', value: formatDateTime(job.started_at), mono: true }
      : null,
    job.completed_at
      ? {
          key: 'completed',
          value: formatDateTime(job.completed_at),
          mono: true,
        }
      : null,
    duration != null
      ? { key: 'duration', value: formatDuration(duration), mono: true }
      : null,
    job.retry_count
      ? { key: 'retries', value: String(job.retry_count), mono: true }
      : null,
    job.last_heartbeat_at
      ? {
          key: 'last heartbeat',
          value: formatDateTime(job.last_heartbeat_at),
          mono: true,
        }
      : null,
  ].filter(Boolean) as Array<KVRow>

  return (
    <div className="mx-auto max-w-[1280px] px-6 py-6 grid gap-5">
      <div>
        <Button
          variant="ghost"
          size="xs"
          asChild
          leading={<ArrowLeft className="h-3 w-3" />}
        >
          <Link {...paths.jobs}>back to jobs</Link>
        </Button>
        <div className="mt-2 flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="mono-label text-[var(--ink-muted)] inline-flex items-center gap-1.5">
              <StatusDot status={job.status} />
              {job.job_type.toUpperCase()} JOB
            </div>
            <h1 className="mt-1 font-mono text-[20px] text-[var(--ink)]">
              {job.id}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge tone={toneForStatus(job.status)}>{job.status}</Badge>
              {duration != null && (
                <span className="font-mono text-[11.5px] text-[var(--ink-muted)]">
                  {formatDuration(duration)}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {!terminal && (
              <Button
                variant="secondary"
                size="sm"
                leading={<X className="h-3.5 w-3.5" />}
                disabled={cancelMutation.isPending}
                onClick={() => {
                  if (confirm('Cancel this job?')) cancelMutation.mutate()
                }}
              >
                Cancel
              </Button>
            )}
            {job.status === 'failed' && (
              <Button
                size="sm"
                leading={<RotateCw className="h-3.5 w-3.5" />}
                disabled={retryMutation.isPending}
                onClick={() => retryMutation.mutate()}
              >
                Retry
              </Button>
            )}
          </div>
        </div>
      </div>

      <Card>
        <CardHeader title="PROGRESS" />
        <CardBody className="grid gap-3">
          <Progress value={job.progress} height={6} showLabel />
          {job.current_step && (
            <div className="mono-label inline-flex items-center gap-2">
              CURRENT STEP
              <span className="font-mono text-[12px] normal-case tracking-normal text-[var(--ink)]">
                {job.current_step}
              </span>
            </div>
          )}
        </CardBody>
      </Card>

      {job.error && (
        <Card>
          <CardHeader
            title="ERROR"
            actions={
              <Badge tone="bad" size="sm">
                failed
              </Badge>
            }
          />
          <CardBody>
            <pre className="overflow-x-auto rounded-[3px] border border-[var(--bad)]/30 bg-[var(--bad-soft)] p-3 font-mono text-[11.5px] leading-relaxed text-[var(--ink)]">
              {job.error}
            </pre>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="DETAILS" />
        <CardBody>
          <KeyValueGrid rows={rows} dense />
        </CardBody>
      </Card>

      {Object.keys(job.metadata).length > 0 && (
        <Card>
          <CardHeader
            title={
              <button
                type="button"
                onClick={() => setShowMeta((v) => !v)}
                className="inline-flex items-center gap-1.5"
              >
                METADATA
                <ChevronDown
                  className={`h-3 w-3 transition-transform ${showMeta ? 'rotate-180' : ''}`}
                />
              </button>
            }
          />
          {showMeta && (
            <CardBody>
              <pre className="overflow-x-auto rounded-[3px] border border-[var(--rule)] bg-[var(--surface-2)] p-3 font-mono text-[11px] leading-relaxed text-[var(--ink-dim)]">
                {JSON.stringify(job.metadata, null, 2)}
              </pre>
            </CardBody>
          )}
        </Card>
      )}
    </div>
  )
}
