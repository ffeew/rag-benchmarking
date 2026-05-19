import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Activity, Layers } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Pagination } from '#/components/ui/pagination'
import { Skeleton } from '#/components/ui/skeleton'
import { StatusDot } from '#/components/ui/status-dot'
import { EmptyState } from '#/components/data/EmptyState'
import { ErrorState } from '#/components/data/ErrorState'
import { KeyValueGrid } from '#/components/data/KeyValueGrid'
import { api } from '#/lib/api'
import {
  formatDate,
  formatDuration,
  formatNumber,
  truncateId,
} from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/datasets/$datasetId/ingestion')({
  component: IngestionPage,
})

function IngestionPage() {
  const { datasetId } = Route.useParams()
  const { token, isAuthed } = useToken()

  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    setOffset(0)
  }, [limit])

  const runsQuery = useQuery({
    queryKey: qk.datasets.ingestionRuns({ datasetId, limit, offset }),
    queryFn: () => api.ingestionRuns(token, datasetId, { limit, offset }),
    enabled: isAuthed,
    placeholderData: keepPreviousData,
    refetchInterval: 6000,
  })

  const runs = runsQuery.data?.items ?? []
  const total = runsQuery.data?.total ?? 0

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6">
      <Card>
        <CardHeader
          title={
            <span>
              INGESTION RUNS{' '}
              <span className="font-mono numeric text-[var(--ink-muted)]">
                · {runs.length}/{total}
              </span>
            </span>
          }
          subtitle={`${total} historical run${total === 1 ? '' : 's'}`}
        />
        <CardBody padded={false}>
          {runsQuery.isLoading ? (
            <div className="p-4 grid gap-1.5">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-14" />
              ))}
            </div>
          ) : runsQuery.isError ? (
            <ErrorState
              error={runsQuery.error}
              onRetry={() => runsQuery.refetch()}
            />
          ) : runs.length === 0 ? (
            <EmptyState
              icon={Activity}
              title="No ingestion runs yet"
              description="Upload or import documents to populate this history."
            />
          ) : (
            <ul className="divide-y divide-[var(--rule)]">
              {runs.map((run) => {
                const chunkCount = run.counts.chunks
                const pageCount = run.counts.pages
                const totalMs = computeTotal(run.timings)

                return (
                  <li
                    key={run.id}
                    className="grid gap-3 px-4 py-3 lg:grid-cols-[16px_minmax(0,1fr)_auto]"
                  >
                    <StatusDot status={run.status} />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[12px] text-[var(--ink)]">
                          {truncateId(run.id)}
                        </span>
                        <Badge tone={toneForStatus(run.status)} size="sm">
                          {run.status}
                        </Badge>
                        {run.embedding_model && (
                          <Badge tone="cite" size="sm">
                            {run.embedding_model}
                          </Badge>
                        )}
                        {run.job_id && (
                          <Link
                            {...paths.job(run.job_id)}
                            className="font-mono text-[10.5px] text-[var(--accent)] hover:underline"
                          >
                            job {truncateId(run.job_id, 6, 3)}
                          </Link>
                        )}
                        <span className="ml-auto font-mono text-[10.5px] text-[var(--ink-muted)]">
                          {formatDate(run.created_at)}
                        </span>
                      </div>

                      <div className="mt-2 grid gap-3 md:grid-cols-2">
                        <KeyValueGrid
                          dense
                          rows={[
                            {
                              key: 'chunks',
                              value:
                                chunkCount != null
                                  ? formatNumber(Number(chunkCount))
                                  : '—',
                              mono: true,
                            },
                            {
                              key: 'pages',
                              value:
                                pageCount != null
                                  ? formatNumber(Number(pageCount))
                                  : '—',
                              mono: true,
                            },
                            {
                              key: 'duration',
                              value: formatDuration(totalMs),
                              mono: true,
                            },
                          ]}
                        />
                        {run.error_summary && (
                          <p className="font-mono text-[11px] text-[var(--bad)] leading-relaxed border-l border-[var(--bad)] pl-2">
                            {run.error_summary}
                          </p>
                        )}
                      </div>
                    </div>
                    <Layers className="h-4 w-4 text-[var(--ink-muted)]" />
                  </li>
                )
              })}
            </ul>
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

function computeTotal(timings: Record<string, unknown>): number {
  let total = 0
  for (const v of Object.values(timings)) {
    if (typeof v === 'number') total += v
  }
  return total
}
