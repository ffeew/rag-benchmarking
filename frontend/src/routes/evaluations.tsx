import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { BarChart3, Scale } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Checkbox } from '#/components/ui/checkbox'
import { Select } from '#/components/ui/input'
import { Pagination } from '#/components/ui/pagination'
import { Skeleton } from '#/components/ui/skeleton'
import { StatusDot } from '#/components/ui/status-dot'
import { EmptyState } from '#/components/data/EmptyState'
import { ErrorState } from '#/components/data/ErrorState'
import { LiveRelative } from '#/components/data/LiveTime'
import { api } from '#/lib/api'
import { truncateId } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/evaluations')({
  component: EvaluationsList,
})

function EvaluationsList() {
  const { token, isAuthed } = useToken()
  const [datasetFilter, setDatasetFilter] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    setOffset(0)
    setSelected(new Set())
  }, [datasetFilter, limit])

  const datasetsQuery = useQuery({
    queryKey: qk.datasets.list({ limit: 200, offset: 0 }),
    queryFn: () => api.datasets(token, { limit: 200 }),
    enabled: isAuthed,
  })

  const evalsQuery = useQuery({
    queryKey: qk.evaluations.list({
      datasetId: datasetFilter || undefined,
      limit,
      offset,
    }),
    queryFn: () =>
      api.evaluations(token, {
        dataset_id: datasetFilter || undefined,
        limit,
        offset,
      }),
    enabled: isAuthed,
    placeholderData: keepPreviousData,
    refetchInterval: 7000,
  })

  const runs = evalsQuery.data?.items ?? []
  const total = evalsQuery.data?.total ?? 0

  const datasetNameById = useMemo(() => {
    const map = new Map<string, string>()
    for (const d of datasetsQuery.data?.items ?? []) map.set(d.id, d.name)
    return map
  }, [datasetsQuery.data])

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectedRuns = runs.filter((r) => selected.has(r.id))
  const sharedDatasetId =
    selectedRuns.length >= 2 &&
    selectedRuns.every((r) => r.dataset_id === selectedRuns[0].dataset_id)
      ? selectedRuns[0].dataset_id
      : null
  const compareLink = sharedDatasetId
    ? paths.evaluationCompare(sharedDatasetId, Array.from(selected).join(','))
    : null

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6 grid gap-5">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mono-label text-[var(--ink-muted)]">EVALS</div>
          <h1 className="mt-1 text-[24px] leading-tight font-semibold tracking-tight">
            Evaluations
          </h1>
          <p className="mt-1 text-[13px] text-[var(--ink-dim)]">
            Every evaluation run across all datasets. Open a dataset to start a
            new run; select 2+ runs from the same dataset here to compare.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3 text-[11.5px]">
          <span className="inline-flex items-center gap-1.5">
            <span className="font-mono numeric text-[var(--ink-dim)]">
              {total}
            </span>
            <span className="mono-label">TOTAL</span>
          </span>
        </div>
      </header>

      <Card>
        <CardHeader
          title={
            <span>
              ALL RUNS{' '}
              <span className="font-mono numeric text-[var(--ink-muted)]">
                · {runs.length}/{total}
              </span>
            </span>
          }
          actions={
            <div className="flex items-center gap-2">
              <Select
                value={datasetFilter}
                onChange={(e) => setDatasetFilter(e.target.value)}
                className="h-7 w-[200px] text-[12px]"
              >
                <option value="">All datasets</option>
                {(datasetsQuery.data?.items ?? []).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </Select>
              {selected.size > 0 && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!compareLink}
                  asChild={!!compareLink}
                  leading={<Scale className="h-3.5 w-3.5" />}
                  title={
                    selected.size < 2
                      ? 'Select 2+ runs'
                      : !sharedDatasetId
                        ? 'Runs must share a dataset'
                        : undefined
                  }
                >
                  {compareLink ? (
                    <Link {...compareLink}>Compare {selected.size}</Link>
                  ) : (
                    <span>Compare {selected.size}</span>
                  )}
                </Button>
              )}
            </div>
          }
        />
        <CardBody padded={false}>
          {evalsQuery.isLoading ? (
            <div className="p-4 grid gap-1.5">
              {Array.from({ length: 6 }).map((_, i) => (
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
              title={total === 0 ? 'No evaluations yet' : 'No matches'}
              description={
                total === 0
                  ? 'Open a dataset and run an evaluation to compare retrieval modes on a case set.'
                  : 'No runs match the dataset filter.'
              }
              action={
                total === 0 ? (
                  <Button asChild>
                    <Link {...paths.datasets}>Browse datasets</Link>
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <ul className="divide-y divide-[var(--rule)]">
              {runs.map((run) => {
                const aggregate = computeAggregate(run.metrics)
                const datasetName =
                  datasetNameById.get(run.dataset_id) ?? truncateId(run.dataset_id)
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
                      {...paths.evaluation(run.dataset_id, run.id)}
                      className="min-w-0 block"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[12.5px] text-[var(--ink)]">
                          {truncateId(run.id)}
                        </span>
                        <Badge tone={toneForStatus(run.status)} size="sm">
                          {run.status}
                        </Badge>
                        <span className="font-mono text-[11px] text-[var(--ink-dim)]">
                          {datasetName}
                        </span>
                        <span className="text-[11.5px] text-[var(--ink-muted)]">
                          variants {run.system_variant}
                        </span>
                      </div>
                      <div className="font-mono text-[10.5px] text-[var(--ink-muted)] mt-0.5">
                        {run.results.length} result
                        {run.results.length === 1 ? '' : 's'} ·{' '}
                        <LiveRelative value={run.created_at} />
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
