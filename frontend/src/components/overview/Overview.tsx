import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  Activity,
  ArrowRight,
  Database,
  Inbox,
  ScrollText,
  Search,
} from 'lucide-react'
import { useMemo } from 'react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Progress } from '#/components/ui/progress'
import { Skeleton, SkeletonRows } from '#/components/ui/skeleton'
import { StatusDot } from '#/components/ui/status-dot'
import { EmptyState } from '#/components/data/EmptyState'
import { MetricNumber } from '#/components/data/MetricNumber'
import { api } from '#/lib/api'
import { formatRelative, truncate, truncateId } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export function Overview() {
  const { token, isAuthed } = useToken()

  // Overview pulls the first page of each list — enough for the summary
  // metrics and the recent-activity strip.
  const datasetsQuery = useQuery({
    queryKey: qk.datasets.list({ limit: 50, offset: 0 }),
    queryFn: () => api.datasets(token, { limit: 50 }),
    enabled: isAuthed,
    staleTime: 15_000,
  })
  const jobsQuery = useQuery({
    queryKey: qk.jobs.list({ limit: 50, offset: 0 }),
    queryFn: () => api.jobs(token, { limit: 50 }),
    enabled: isAuthed,
    refetchInterval: 4500,
  })
  const evaluationsQuery = useQuery({
    queryKey: qk.evaluations.list({ limit: 50, offset: 0 }),
    queryFn: () => api.evaluations(token, { limit: 50 }),
    enabled: isAuthed,
    refetchInterval: 8000,
  })
  const tracesQuery = useQuery({
    queryKey: qk.traces.list(),
    queryFn: () => api.traces(token, { limit: 6 }).catch(() => []),
    enabled: isAuthed,
    staleTime: 12_000,
  })
  const readyQuery = useQuery({
    queryKey: qk.ready,
    queryFn: api.ready,
    refetchInterval: 10_000,
  })

  const datasets = datasetsQuery.data?.items ?? []
  const jobs = jobsQuery.data?.items ?? []
  const evaluations = evaluationsQuery.data?.items ?? []
  const traces = tracesQuery.data ?? []

  const totals = useMemo(() => {
    const totalDocuments = datasets.reduce(
      (sum, d) => sum + d.document_count,
      0,
    )
    const totalChunks = datasets.reduce(
      (sum, d) => sum + d.active_chunk_count,
      0,
    )
    const totalIngestions = datasets.reduce(
      (sum, d) => sum + d.completed_ingestion_count,
      0,
    )
    const ingestionCoverage =
      totalDocuments > 0 ? Math.min(1, totalIngestions / totalDocuments) : 0
    const activeJobs = jobs.filter((j) =>
      ['running', 'queued'].includes(j.status),
    ).length
    return {
      totalDocuments,
      totalChunks,
      totalIngestions,
      ingestionCoverage,
      activeJobs,
    }
  }, [datasets, jobs])

  const lastDataset = datasets.at(0)

  return (
    <div className="mx-auto flex max-w-[1440px] flex-col gap-5 px-6 py-6">
      {/* Header strip */}
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mono-label text-[var(--ink-muted)]">OVERVIEW</div>
          <h1 className="mt-1 text-[26px] leading-tight font-semibold tracking-tight">
            Operator console
          </h1>
          <p className="mt-1 text-[13px] text-[var(--ink-dim)]">
            Real-time view of ingestion, retrieval, and evaluation activity.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            asChild
            leading={<Database className="h-3.5 w-3.5" />}
          >
            <Link {...paths.datasets}>Datasets</Link>
          </Button>
          {lastDataset && (
            <Button
              size="sm"
              asChild
              leading={<Search className="h-3.5 w-3.5" />}
            >
              <Link {...paths.datasetQuery(lastDataset.id)}>Run query</Link>
            </Button>
          )}
        </div>
      </header>

      {/* Metric strip */}
      <section className="grid grid-cols-2 gap-px bg-[var(--rule)] border border-[var(--rule)] rounded-[5px] overflow-hidden md:grid-cols-4">
        <MetricCell
          label="DOCUMENTS"
          value={totals.totalDocuments}
          loading={datasetsQuery.isLoading}
        />
        <MetricCell
          label="ACTIVE CHUNKS"
          value={totals.totalChunks}
          loading={datasetsQuery.isLoading}
        />
        <MetricCell
          label="JOBS ACTIVE"
          value={totals.activeJobs}
          unit={`/ ${jobs.length}`}
          loading={jobsQuery.isLoading}
        />
        <MetricCell
          label="INGESTED"
          value={`${Math.round(totals.ingestionCoverage * 100)}%`}
          unit={`${totals.totalIngestions} runs`}
          loading={datasetsQuery.isLoading}
          footer={
            <Progress
              value={totals.ingestionCoverage * 100}
              height={3}
              className="mt-2"
            />
          }
        />
      </section>

      <section className="grid grid-cols-1 gap-5 lg:grid-cols-[2fr_3fr]">
        {/* Datasets quick-list */}
        <Card>
          <CardHeader
            title="DATASETS"
            actions={
              <Button variant="ghost" size="xs" asChild>
                <Link {...paths.datasets}>
                  all <ArrowRight className="h-3 w-3" />
                </Link>
              </Button>
            }
          />
          <CardBody padded={false}>
            {datasetsQuery.isLoading ? (
              <div className="px-4 py-4">
                <SkeletonRows rows={4} />
              </div>
            ) : datasets.length === 0 ? (
              <EmptyState
                icon={Database}
                title="No datasets yet"
                description="Create a dataset, then upload PDFs or import from the local corpus."
                action={
                  <Button asChild size="sm">
                    <Link {...paths.datasets}>Create dataset</Link>
                  </Button>
                }
              />
            ) : (
              <ul>
                {datasets.slice(0, 6).map((d) => (
                  <li
                    key={d.id}
                    className="border-b last:border-b-0 border-[var(--rule)]"
                  >
                    <Link
                      {...paths.dataset(d.id)}
                      className="flex items-center justify-between px-4 py-2.5 hover:bg-[var(--surface-2)] transition-colors"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-[var(--ink)] truncate text-[13px]">
                            {d.name}
                          </span>
                          {d.completed_ingestion_count > 0 &&
                            d.document_count > 0 &&
                            d.completed_ingestion_count >= d.document_count && (
                              <Badge tone="ok" size="sm">
                                ready
                              </Badge>
                            )}
                        </div>
                        {d.description && (
                          <div className="text-[11.5px] text-[var(--ink-muted)] truncate">
                            {d.description}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-4 ml-3">
                        <span className="font-mono numeric text-[11px] text-[var(--ink-dim)]">
                          {d.document_count} docs
                        </span>
                        <span className="font-mono numeric text-[11px] text-[var(--ink-muted)]">
                          {d.active_chunk_count.toLocaleString()} chunks
                        </span>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        {/* Recent activity column */}
        <div className="grid gap-5">
          <Card>
            <CardHeader
              title="RECENT JOBS"
              actions={
                <Button variant="ghost" size="xs" asChild>
                  <Link {...paths.jobs}>
                    all <ArrowRight className="h-3 w-3" />
                  </Link>
                </Button>
              }
            />
            <CardBody padded={false}>
              {jobsQuery.isLoading ? (
                <div className="px-4 py-4">
                  <SkeletonRows rows={4} />
                </div>
              ) : jobs.length === 0 ? (
                <EmptyState
                  icon={Inbox}
                  title="No jobs yet"
                  description="Ingestion or evaluation jobs will appear here once started."
                />
              ) : (
                <ul>
                  {jobs.slice(0, 5).map((j) => (
                    <li
                      key={j.id}
                      className="border-b last:border-b-0 border-[var(--rule)]"
                    >
                      <Link
                        {...paths.job(j.id)}
                        className="grid grid-cols-[16px_1fr_auto] items-center gap-3 px-4 py-2.5 hover:bg-[var(--surface-2)] transition-colors"
                      >
                        <StatusDot status={j.status} />
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 text-[12.5px]">
                            <span className="font-mono uppercase text-[11px] tracking-wide text-[var(--ink-muted)]">
                              {j.job_type}
                            </span>
                            <span className="text-[var(--ink-muted)]">·</span>
                            <span className="font-mono text-[11px] text-[var(--ink-dim)]">
                              {truncateId(j.id, 6, 3)}
                            </span>
                            <Badge tone={toneForStatus(j.status)} size="sm">
                              {j.status}
                            </Badge>
                          </div>
                          {j.current_step ? (
                            <div className="text-[11.5px] text-[var(--ink-muted)] truncate">
                              {j.current_step}
                            </div>
                          ) : j.error ? (
                            <div className="text-[11.5px] text-[var(--bad)] truncate font-mono">
                              {truncate(j.error, 80)}
                            </div>
                          ) : null}
                        </div>
                        <div className="flex flex-col items-end gap-1 min-w-[110px]">
                          <Progress value={j.progress} className="w-24" />
                          <span className="font-mono numeric text-[10.5px] text-[var(--ink-muted)]">
                            {formatRelative(j.created_at)}
                          </span>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="RECENT QUERIES"
              actions={
                <Button variant="ghost" size="xs" asChild>
                  <Link {...paths.traces}>
                    all <ArrowRight className="h-3 w-3" />
                  </Link>
                </Button>
              }
            />
            <CardBody padded={false}>
              {tracesQuery.isLoading ? (
                <div className="px-4 py-4">
                  <SkeletonRows rows={3} />
                </div>
              ) : traces.length === 0 ? (
                <EmptyState
                  icon={ScrollText}
                  title="No traces yet"
                  description="Questions you ask in the query workspace will appear here for inspection."
                />
              ) : (
                <ul>
                  {traces.slice(0, 5).map((t) => (
                    <li
                      key={t.id}
                      className="border-b last:border-b-0 border-[var(--rule)]"
                    >
                      <Link
                        {...paths.trace(t.id)}
                        className="flex items-start gap-3 px-4 py-2.5 hover:bg-[var(--surface-2)] transition-colors"
                      >
                        <div className="flex h-5 items-center">
                          <Badge tone="cite" size="sm">
                            {t.retrieval_mode.replace('_', ' ')}
                          </Badge>
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-[12.5px] text-[var(--ink)] truncate">
                            {t.user_question}
                          </div>
                          <div className="font-mono text-[10.5px] text-[var(--ink-muted)]">
                            {truncateId(t.id)} · {formatRelative(t.created_at)}
                          </div>
                        </div>
                        {t.confidence != null && (
                          <span className="font-mono numeric text-[11px] text-[var(--ink-dim)]">
                            {Math.round(t.confidence * 100)}%
                          </span>
                        )}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>
      </section>

      {/* Evaluations + Health rail */}
      <section className="grid grid-cols-1 gap-5 lg:grid-cols-[3fr_2fr]">
        <Card>
          <CardHeader
            title="RECENT EVALUATIONS"
            actions={
              <Button variant="ghost" size="xs" asChild>
                <Link {...paths.evaluations}>
                  all <ArrowRight className="h-3 w-3" />
                </Link>
              </Button>
            }
          />
          <CardBody padded={false}>
            {evaluationsQuery.isLoading ? (
              <div className="px-4 py-4">
                <SkeletonRows rows={3} />
              </div>
            ) : evaluations.length === 0 ? (
              <EmptyState
                icon={Activity}
                title="No evaluations yet"
                description="Run an evaluation against a curated test set to compare full-agentic, single-pass, and LLM-only modes."
              />
            ) : (
              <ul>
                {evaluations.slice(0, 4).map((e) => (
                  <li
                    key={e.id}
                    className="border-b last:border-b-0 border-[var(--rule)]"
                  >
                    <div className="grid grid-cols-[16px_1fr_auto] items-center gap-3 px-4 py-2.5">
                      <StatusDot status={e.status} />
                      <div className="min-w-0">
                        <div className="font-mono text-[11.5px] text-[var(--ink-dim)] truncate">
                          {truncateId(e.id)}
                        </div>
                        <div className="text-[11.5px] text-[var(--ink-muted)] truncate">
                          variants: {e.system_variant}
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-0.5">
                        <Badge tone={toneForStatus(e.status)} size="sm">
                          {e.status}
                        </Badge>
                        <span className="font-mono numeric text-[10.5px] text-[var(--ink-muted)]">
                          {e.results.length} results
                        </span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="SYSTEM HEALTH" />
          <CardBody>
            {readyQuery.isLoading ? (
              <SkeletonRows rows={4} />
            ) : !readyQuery.data ? (
              <EmptyState
                title="No status"
                description="Backend /ready is not responding."
              />
            ) : (
              <ul className="grid gap-2">
                <HealthRow
                  label="API"
                  ok={readyQuery.data.status === 'ready'}
                  detail={readyQuery.data.status}
                />
                <HealthRow label="DATABASE" ok={readyQuery.data.database} />
                <HealthRow label="MINIO" ok={readyQuery.data.minio} />
                <HealthRow label="REDIS / CELERY" ok={readyQuery.data.redis} />
                <li className="mt-2 border-t border-[var(--rule)] pt-2">
                  <div className="flex items-center justify-between">
                    <span className="mono-label">PROVIDER MODE</span>
                    <Badge
                      tone={
                        readyQuery.data.providers.allow_mock_providers
                          ? 'warn'
                          : 'ok'
                      }
                      size="sm"
                    >
                      {readyQuery.data.providers.allow_mock_providers
                        ? 'mock'
                        : 'live'}
                    </Badge>
                  </div>
                </li>
              </ul>
            )}
          </CardBody>
        </Card>
      </section>
    </div>
  )
}

function MetricCell({
  label,
  value,
  unit,
  loading,
  footer,
}: {
  label: string
  value: number | string
  unit?: string
  loading?: boolean
  footer?: React.ReactNode
}) {
  return (
    <div className="bg-[var(--surface)] px-4 py-4">
      {loading ? (
        <>
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-2 h-7 w-24" />
        </>
      ) : (
        <MetricNumber label={label} value={value} unit={unit} />
      )}
      {footer}
    </div>
  )
}

function HealthRow({
  label,
  ok,
  detail,
}: {
  label: string
  ok: boolean
  detail?: string
}) {
  return (
    <li className="flex items-center justify-between">
      <span className="mono-label">{label}</span>
      <span className="inline-flex items-center gap-1.5">
        <StatusDot status={ok ? 'ready' : 'failed'} pulse={!ok} />
        <span
          className={`font-mono text-[11px] uppercase ${ok ? 'text-[var(--ok)]' : 'text-[var(--bad)]'}`}
        >
          {detail ?? (ok ? 'ready' : 'down')}
        </span>
      </span>
    </li>
  )
}
