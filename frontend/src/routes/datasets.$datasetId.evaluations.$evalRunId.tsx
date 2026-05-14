import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, ExternalLink, Scale } from 'lucide-react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Skeleton } from '#/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '#/components/ui/table'
import { ErrorState } from '#/components/data/ErrorState'
import { MetricNumber } from '#/components/data/MetricNumber'
import { api } from '#/lib/api'
import { formatDateTime, formatPercent, truncateId } from '#/lib/format'
import { isTerminalJobStatus, nextJobInterval } from '#/lib/polling'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute(
  '/datasets/$datasetId/evaluations/$evalRunId',
)({
  component: EvalDetail,
})

function EvalDetail() {
  const { datasetId, evalRunId } = Route.useParams()
  const { token, isAuthed } = useToken()

  const evalQuery = useQuery({
    queryKey: qk.evaluations.detail(evalRunId),
    queryFn: () => api.evaluation(token, evalRunId),
    enabled: isAuthed,
    refetchInterval: (q) => nextJobInterval(q.state.data?.status, 4500),
  })

  if (evalQuery.isLoading) {
    return (
      <div className="p-6 grid gap-3">
        <Skeleton className="h-6 w-72" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  if (evalQuery.isError || !evalQuery.data) {
    return (
      <ErrorState
        title="Evaluation not found"
        error={evalQuery.error}
        onRetry={() => evalQuery.refetch()}
      />
    )
  }

  const run = evalQuery.data
  const metricEntries = Object.entries(run.metrics).filter(
    ([, v]) => typeof v === 'number',
  ) as Array<[string, number]>
  const isRunning = !isTerminalJobStatus(run.status)

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6 grid gap-5">
      <div>
        <Button
          variant="ghost"
          size="xs"
          asChild
          leading={<ArrowLeft className="h-3 w-3" />}
        >
          <Link {...paths.datasetEvaluations(datasetId)}>
            back to evaluations
          </Link>
        </Button>
        <div className="mt-2 flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="mono-label text-[var(--ink-muted)]">EVAL RUN</div>
            <h1 className="mt-1 font-mono text-[20px] text-[var(--ink)]">
              {truncateId(run.id, 12, 6)}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge tone={toneForStatus(run.status)}>{run.status}</Badge>
              <span className="text-[11.5px] text-[var(--ink-muted)] font-mono">
                variants {run.system_variant}
              </span>
              <span className="text-[11.5px] text-[var(--ink-muted)] font-mono">
                {formatDateTime(run.created_at)}
              </span>
            </div>
          </div>
          <Button
            variant="secondary"
            size="sm"
            asChild
            leading={<Scale className="h-3.5 w-3.5" />}
          >
            <Link {...paths.evaluationCompare(datasetId, run.id)}>Compare</Link>
          </Button>
        </div>
      </div>

      {metricEntries.length > 0 && (
        <section className="grid grid-cols-2 gap-px bg-[var(--rule)] border border-[var(--rule)] rounded-[5px] overflow-hidden md:grid-cols-4">
          {metricEntries.slice(0, 4).map(([key, value]) => (
            <div key={key} className="bg-[var(--surface)] px-4 py-4">
              <MetricNumber
                label={key.replace(/_/g, ' ').toUpperCase()}
                value={value <= 1 ? formatPercent(value) : value.toFixed(2)}
                size="md"
              />
            </div>
          ))}
        </section>
      )}

      <Card>
        <CardHeader
          title={
            <span>
              CASE RESULTS{' '}
              <span className="font-mono numeric text-[var(--ink-muted)]">
                {run.results.length}
              </span>
            </span>
          }
          actions={
            isRunning ? (
              <Badge tone="warn" size="sm">
                streaming
              </Badge>
            ) : null
          }
        />
        <CardBody padded={false}>
          {run.results.length === 0 ? (
            <p className="px-4 py-6 text-center text-[12.5px] text-[var(--ink-muted)]">
              No results yet.
            </p>
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>MODE</TH>
                  <TH>ANSWER</TH>
                  <TH>METRICS</TH>
                  <TH>TRACE</TH>
                </tr>
              </THead>
              <TBody>
                {run.results.map((r) => {
                  const metricsList = Object.entries(r.metrics).filter(
                    ([, v]) => typeof v === 'number',
                  ) as Array<[string, number]>
                  return (
                    <TR key={r.id}>
                      <TD>
                        <Badge tone="cite" size="sm">
                          {r.retrieval_mode.replace('_', ' ')}
                        </Badge>
                      </TD>
                      <TD className="max-w-[480px]">
                        {r.error ? (
                          <span className="font-mono text-[var(--bad)]">
                            {r.error}
                          </span>
                        ) : (
                          <span className="text-[12px] text-[var(--ink)] leading-relaxed line-clamp-2">
                            {r.answer ?? '–'}
                          </span>
                        )}
                      </TD>
                      <TD>
                        <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10.5px]">
                          {metricsList.slice(0, 4).map(([k, v]) => (
                            <span key={k} className="text-[var(--ink-dim)]">
                              <span className="text-[var(--ink-muted)]">
                                {k.split('_')[0]}
                              </span>{' '}
                              <span className="numeric text-[var(--ink)]">
                                {v <= 1
                                  ? `${Math.round(v * 100)}%`
                                  : v.toFixed(2)}
                              </span>
                            </span>
                          ))}
                        </div>
                      </TD>
                      <TD>
                        {r.trace_id ? (
                          <Link
                            {...paths.trace(r.trace_id)}
                            className="inline-flex items-center gap-1 font-mono text-[11px] text-[var(--accent)] hover:underline"
                          >
                            view <ExternalLink className="h-3 w-3" />
                          </Link>
                        ) : (
                          <span className="text-[var(--ink-muted)]">—</span>
                        )}
                      </TD>
                    </TR>
                  )
                })}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
