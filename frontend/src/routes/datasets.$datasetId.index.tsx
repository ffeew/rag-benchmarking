import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Activity, ArrowRight, Database } from 'lucide-react'
import { useMemo } from 'react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Skeleton } from '#/components/ui/skeleton'
import { StatusDot } from '#/components/ui/status-dot'
import { EmptyState } from '#/components/data/EmptyState'
import { api } from '#/lib/api'
import { formatRelative, truncate, truncateId } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/datasets/$datasetId/')({
  component: DatasetSummary,
})

function DatasetSummary() {
  const { datasetId } = Route.useParams()
  const { token, isAuthed } = useToken()

  // Overview cards need broad coverage but not full pagination — pull a
  // capped page (200) for ticker/form breakdowns; click-through shows everything.
  const documentsQuery = useQuery({
    queryKey: qk.datasets.documents({ datasetId, limit: 200, offset: 0 }),
    queryFn: () => api.documents(token, datasetId, { limit: 200 }),
    enabled: isAuthed,
  })

  const jobsQuery = useQuery({
    queryKey: qk.jobs.list({ datasetId, limit: 50, offset: 0 }),
    queryFn: () => api.jobs(token, { dataset_id: datasetId, limit: 50 }),
    enabled: isAuthed,
    refetchInterval: 4500,
  })

  const evalsQuery = useQuery({
    queryKey: qk.evaluations.list({ datasetId, limit: 50, offset: 0 }),
    queryFn: () => api.evaluations(token, { dataset_id: datasetId, limit: 50 }),
    enabled: isAuthed,
  })

  const documents = documentsQuery.data?.items ?? []
  const jobs = jobsQuery.data?.items ?? []
  const evaluations = evalsQuery.data?.items ?? []

  const tickerCounts = useMemo(() => {
    const map = new Map<string, number>()
    for (const d of documents) {
      map.set(d.ticker, (map.get(d.ticker) ?? 0) + 1)
    }
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1])
  }, [documents])

  const formCounts = useMemo(() => {
    const map = new Map<string, number>()
    for (const d of documents) {
      map.set(d.form_type, (map.get(d.form_type) ?? 0) + 1)
    }
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1])
  }, [documents])

  const maxTickerCount = tickerCounts[0]?.[1] ?? 1
  const maxFormCount = formCounts[0]?.[1] ?? 1

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6">
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[2fr_1fr]">
        <div className="grid gap-5">
          <Card>
            <CardHeader
              title="DOCUMENT BREAKDOWN"
              actions={
                <Button variant="ghost" size="xs" asChild>
                  <Link {...paths.datasetDocuments(datasetId)}>
                    documents <ArrowRight className="h-3 w-3" />
                  </Link>
                </Button>
              }
            />
            <CardBody>
              {documentsQuery.isLoading ? (
                <Skeleton className="h-32" />
              ) : documents.length === 0 ? (
                <EmptyState
                  icon={Database}
                  title="No documents"
                  description="Upload PDFs or import from the local corpus to begin."
                  action={
                    <Button asChild size="sm">
                      <Link {...paths.datasetDocuments(datasetId)}>
                        Manage documents
                      </Link>
                    </Button>
                  }
                />
              ) : (
                <div className="grid gap-5 md:grid-cols-2">
                  <div>
                    <div className="mono-label mb-2">BY TICKER (top 10)</div>
                    <ul className="grid gap-1.5">
                      {tickerCounts.slice(0, 10).map(([ticker, count]) => (
                        <li key={ticker} className="flex items-center gap-2">
                          <span className="font-mono text-[12px] text-[var(--ink)] w-12 shrink-0">
                            {ticker}
                          </span>
                          <div className="relative flex-1 h-3.5 bg-[var(--surface-2)] rounded-[2px] overflow-hidden">
                            <div
                              className="absolute inset-y-0 left-0 bg-[var(--accent)] opacity-80"
                              style={{
                                width: `${(count / maxTickerCount) * 100}%`,
                              }}
                            />
                          </div>
                          <span className="font-mono numeric text-[11px] text-[var(--ink-dim)] w-8 text-right">
                            {count}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="mono-label mb-2">BY FORM</div>
                    <ul className="grid gap-1.5">
                      {formCounts.map(([form, count]) => (
                        <li key={form} className="flex items-center gap-2">
                          <span className="font-mono text-[12px] text-[var(--ink)] w-14 shrink-0 uppercase">
                            {form}
                          </span>
                          <div className="relative flex-1 h-3.5 bg-[var(--surface-2)] rounded-[2px] overflow-hidden">
                            <div
                              className="absolute inset-y-0 left-0 bg-[var(--cite)] opacity-70"
                              style={{
                                width: `${(count / maxFormCount) * 100}%`,
                              }}
                            />
                          </div>
                          <span className="font-mono numeric text-[11px] text-[var(--ink-dim)] w-8 text-right">
                            {count}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="RECENT EVALUATIONS"
              actions={
                <Button variant="ghost" size="xs" asChild>
                  <Link {...paths.datasetEvaluations(datasetId)}>
                    all <ArrowRight className="h-3 w-3" />
                  </Link>
                </Button>
              }
            />
            <CardBody padded={false}>
              {evalsQuery.isLoading ? (
                <div className="p-4 grid gap-1.5">
                  {Array.from({ length: 2 }).map((_, i) => (
                    <Skeleton key={i} className="h-7" />
                  ))}
                </div>
              ) : evaluations.length === 0 ? (
                <EmptyState
                  icon={Activity}
                  title="No evaluations yet"
                  description="Run an evaluation to compare full-agentic, single-pass, and LLM-only modes."
                />
              ) : (
                <ul>
                  {evaluations.slice(0, 4).map((e) => (
                    <li
                      key={e.id}
                      className="border-b last:border-b-0 border-[var(--rule)]"
                    >
                      <div className="grid grid-cols-[16px_1fr_auto] items-center gap-3 px-4 py-2">
                        <StatusDot status={e.status} />
                        <div className="min-w-0">
                          <div className="font-mono text-[11.5px] text-[var(--ink-dim)]">
                            {truncateId(e.id)}
                          </div>
                          <div className="text-[11.5px] text-[var(--ink-muted)]">
                            variants {e.system_variant}
                          </div>
                        </div>
                        <Badge tone={toneForStatus(e.status)} size="sm">
                          {e.status}
                        </Badge>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>

        <Card>
          <CardHeader
            title="JOB ACTIVITY"
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
              <div className="p-4 grid gap-1.5">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-7" />
                ))}
              </div>
            ) : jobs.length === 0 ? (
              <EmptyState
                icon={Activity}
                title="No jobs"
                description="Ingestion and evaluation activity appears here."
              />
            ) : (
              <ul>
                {jobs.slice(0, 8).map((j) => (
                  <li
                    key={j.id}
                    className="border-b last:border-b-0 border-[var(--rule)]"
                  >
                    <Link
                      {...paths.job(j.id)}
                      className="grid grid-cols-[16px_1fr] items-center gap-3 px-4 py-2 hover:bg-[var(--surface-2)] transition-colors"
                    >
                      <StatusDot status={j.status} />
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 text-[11.5px]">
                          <span className="font-mono uppercase text-[var(--ink-muted)]">
                            {j.job_type}
                          </span>
                          <Badge tone={toneForStatus(j.status)} size="sm">
                            {j.status}
                          </Badge>
                          <span className="ml-auto font-mono numeric text-[10.5px] text-[var(--ink-muted)]">
                            {formatRelative(j.created_at)}
                          </span>
                        </div>
                        {(j.current_step || j.error) && (
                          <div
                            className={`text-[11px] truncate mt-0.5 ${j.error ? 'text-[var(--bad)] font-mono' : 'text-[var(--ink-muted)]'}`}
                          >
                            {truncate(j.error ?? j.current_step ?? '', 80)}
                          </div>
                        )}
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}
