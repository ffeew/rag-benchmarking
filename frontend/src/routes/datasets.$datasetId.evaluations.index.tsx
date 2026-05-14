import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { BarChart3, Scale } from 'lucide-react'
import { useState } from 'react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Checkbox } from '#/components/ui/checkbox'
import { Pagination } from '#/components/ui/pagination'
import { Skeleton } from '#/components/ui/skeleton'
import { StatusDot } from '#/components/ui/status-dot'
import { EmptyState } from '#/components/data/EmptyState'
import { ErrorState } from '#/components/data/ErrorState'
import { NewEvaluationDialog } from '#/components/eval/NewEvaluationDialog'
import { api } from '#/lib/api'
import { formatRelative, truncateId } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/datasets/$datasetId/evaluations/')({
  component: EvaluationsList,
})

function EvaluationsList() {
  const { datasetId } = Route.useParams()
  const { token, isAuthed } = useToken()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)

  const evalsQuery = useQuery({
    queryKey: qk.evaluations.list({ datasetId, limit, offset }),
    queryFn: () => api.evaluations(token, { dataset_id: datasetId, limit, offset }),
    enabled: isAuthed,
    placeholderData: keepPreviousData,
    refetchInterval: 7000,
  })

  const runs = evalsQuery.data?.items ?? []
  const total = evalsQuery.data?.total ?? 0

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const compareUrl =
    selected.size >= 2
      ? `${paths.evaluationCompare(datasetId)}?runs=${Array.from(selected).join(',')}`
      : null

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6 grid gap-5">
      <Card>
        <CardHeader
          title="EVALUATION RUNS"
          actions={
            <div className="flex items-center gap-2">
              {selected.size > 0 && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={selected.size < 2}
                  asChild={selected.size >= 2}
                  leading={<Scale className="h-3.5 w-3.5" />}
                >
                  {compareUrl ? (
                    <Link to={compareUrl}>Compare {selected.size}</Link>
                  ) : (
                    <span>Compare (select 2+)</span>
                  )}
                </Button>
              )}
              <NewEvaluationDialog datasetId={datasetId} />
            </div>
          }
        />
        <CardBody padded={false}>
          {evalsQuery.isLoading ? (
            <div className="p-4 grid gap-1.5">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : evalsQuery.isError ? (
            <ErrorState
              error={evalsQuery.error}
              onRetry={() => evalsQuery.refetch()}
            />
          ) : runs.length === 0 ? (
            <EmptyState
              icon={BarChart3}
              title="No evaluations yet"
              description="Run an evaluation to compare retrieval modes on a curated case set."
              action={<NewEvaluationDialog datasetId={datasetId} />}
            />
          ) : (
            <ul className="divide-y divide-[var(--rule)]">
              {runs.map((run) => {
                const aggregate = computeAggregate(run.metrics)
                return (
                  <li
                    key={run.id}
                    className="grid grid-cols-[24px_16px_1fr_auto] items-center gap-3 px-4 py-2.5 hover:bg-[var(--surface-2)] transition-colors"
                  >
                    <Checkbox
                      checked={selected.has(run.id)}
                      onCheckedChange={() => toggle(run.id)}
                    />
                    <StatusDot status={run.status} />
                    <Link
                      {...paths.evaluation(datasetId, run.id)}
                      className="min-w-0 block"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[12.5px] text-[var(--ink)]">
                          {truncateId(run.id)}
                        </span>
                        <Badge tone={toneForStatus(run.status)} size="sm">
                          {run.status}
                        </Badge>
                        <span className="text-[11.5px] text-[var(--ink-muted)]">
                          variants {run.system_variant}
                        </span>
                      </div>
                      <div className="font-mono text-[10.5px] text-[var(--ink-muted)] mt-0.5">
                        {run.results.length} result
                        {run.results.length === 1 ? '' : 's'} ·{' '}
                        {formatRelative(run.created_at)}
                      </div>
                    </Link>
                    <div className="flex flex-col items-end font-mono text-[11px] text-[var(--ink-dim)]">
                      {aggregate.map((m) => (
                        <span key={m.key} className="numeric">
                          <span className="text-[var(--ink-muted)] text-[10.5px] uppercase tracking-wide mr-1">
                            {m.key}
                          </span>
                          {m.value}
                        </span>
                      ))}
                    </div>
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

function computeAggregate(
  metrics: Record<string, unknown>,
): Array<{ key: string; value: string }> {
  const out: Array<{ key: string; value: string }> = []
  for (const k of [
    'answer_present_rate',
    'expected_contains_rate',
    'citation_hit_rate',
  ]) {
    const v = metrics[k]
    if (typeof v === 'number') {
      out.push({
        key: k.replace(/_/g, ' ').replace(' rate', ''),
        value: `${Math.round(v * 100)}%`,
      })
    }
  }
  return out.slice(0, 3)
}
