import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link, useSearch } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'
import { useMemo } from 'react'
import { z } from 'zod'

import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Skeleton } from '#/components/ui/skeleton'
import { Tooltip } from '#/components/ui/tooltip'
import { ErrorState } from '#/components/data/ErrorState'
import { api } from '#/lib/api'
import type { EvalRun } from '#/lib/api'
import { cn } from '#/lib/cn'
import { formatPercent, truncate, truncateId } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

const searchSchema = z.object({
  runs: z.string().optional(),
})

export const Route = createFileRoute(
  '/datasets/$datasetId/evaluations/compare',
)({
  component: EvalCompare,
  validateSearch: searchSchema,
})

const PRIMARY_METRIC = 'expected_contains_rate'

function EvalCompare() {
  const { datasetId } = Route.useParams()
  const { token, isAuthed } = useToken()
  const search = useSearch({ from: '/datasets/$datasetId/evaluations/compare' })
  const ids = (search.runs ?? '').split(',').filter(Boolean)

  const queries = ids.map((id) =>
    useQuery({
      queryKey: qk.evaluations.detail(id),
      queryFn: () => api.evaluation(token, id),
      enabled: isAuthed && Boolean(id),
    }),
  )

  const loaded = queries.every((q) => q.data) && queries.length > 0
  const error = queries.find((q) => q.error)?.error
  const runs = queries.map((q) => q.data).filter(Boolean) as Array<EvalRun>

  const matrix = useMemo(() => buildMatrix(runs), [runs])

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-6 grid gap-5">
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
        <h1 className="mt-2 text-[22px] leading-tight font-semibold tracking-tight">
          Ablation comparison
        </h1>
        <p className="mt-1 text-[13px] text-[var(--ink-dim)]">
          Side-by-side per-case metrics across runs and retrieval modes.{' '}
          <span className="font-mono text-[var(--ink-muted)]">
            primary metric: {PRIMARY_METRIC}
          </span>
        </p>
      </div>

      {error ? (
        <ErrorState error={error} />
      ) : !loaded ? (
        <div className="grid gap-3">
          <Skeleton className="h-6 w-60" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : ids.length === 0 ? (
        <Card>
          <CardBody>
            <p className="text-[12.5px] text-[var(--ink-muted)]">
              No runs selected. Go back and check at least two runs to compare.
            </p>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader
            title="PIVOT"
            subtitle={`${matrix.cases.length} cases × ${matrix.columns.length} variant${matrix.columns.length === 1 ? '' : 's'}`}
          />
          <CardBody padded={false}>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[12px]">
                <thead>
                  <tr className="bg-[var(--surface-2)] border-b border-[var(--rule)]">
                    <th className="mono-label sticky left-0 z-10 bg-[var(--surface-2)] px-3 py-2 text-left w-[420px] border-r border-[var(--rule)]">
                      CASE
                    </th>
                    {matrix.columns.map((col) => (
                      <th
                        key={col.key}
                        className="px-3 py-2 text-center border-r border-[var(--rule)] min-w-[140px]"
                      >
                        <div className="mono-label">
                          {col.mode.replace('_', ' ')}
                        </div>
                        <div className="font-mono text-[10.5px] text-[var(--ink-muted)] mt-0.5">
                          {truncateId(col.runId, 6, 3)}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {matrix.cases.map((row, idx) => (
                    <tr
                      key={row.key}
                      className={cn(
                        'border-b border-[var(--rule)]',
                        idx % 2 === 1 && 'bg-[var(--surface-2)]/30',
                      )}
                    >
                      <td className="sticky left-0 z-10 bg-inherit px-3 py-2 align-top border-r border-[var(--rule)]">
                        <span className="text-[12px] text-[var(--ink)]">
                          {truncate(row.question, 90)}
                        </span>
                      </td>
                      {matrix.columns.map((col) => {
                        const cell = row.cells.get(col.key)
                        return (
                          <td
                            key={col.key}
                            className="border-r border-[var(--rule)] px-3 py-2 align-top"
                          >
                            {cell ? (
                              <ResultCell run={col.runId} cell={cell} />
                            ) : (
                              <span className="font-mono text-[var(--ink-muted)] text-[11px]">
                                –
                              </span>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                  <tr className="border-t-2 border-[var(--rule-strong)] bg-[var(--surface-2)]">
                    <td className="sticky left-0 bg-[var(--surface-2)] px-3 py-2 mono-label border-r border-[var(--rule)]">
                      MEAN
                    </td>
                    {matrix.columns.map((col) => (
                      <td
                        key={col.key}
                        className="px-3 py-2 text-center border-r border-[var(--rule)] font-mono numeric text-[var(--ink)]"
                      >
                        {matrix.aggregates[col.key] != null
                          ? formatPercent(matrix.aggregates[col.key]!)
                          : '–'}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  )
}

type Cell = {
  metricValue: number | null
  answer: string | null
  traceId: string | null
  error: string | null
}

function ResultCell({ cell }: { run: string; cell: Cell }) {
  const v = cell.metricValue
  const tone =
    v == null
      ? 'text-[var(--ink-muted)]'
      : v >= 0.7
        ? 'text-[var(--ok)]'
        : v >= 0.4
          ? 'text-[var(--warn)]'
          : 'text-[var(--bad)]'
  return (
    <Tooltip
      content={
        <div className="grid gap-1 font-mono text-[11px]">
          <span className="text-[var(--ink-muted)] uppercase tracking-wide">
            answer
          </span>
          <span className="text-[var(--ink)] max-w-[260px]">
            {cell.error
              ? `error: ${cell.error}`
              : truncate(cell.answer ?? '—', 180)}
          </span>
        </div>
      }
      side="bottom"
    >
      <div
        className={cn('flex flex-col items-center gap-0.5 text-center', tone)}
      >
        <span className="font-mono numeric text-[14px]">
          {v == null ? (cell.error ? 'ERR' : '–') : formatPercent(v)}
        </span>
        {cell.traceId && (
          <Link
            {...paths.trace(cell.traceId)}
            className="font-mono text-[10px] text-[var(--ink-muted)] hover:underline"
          >
            trace
          </Link>
        )}
      </div>
    </Tooltip>
  )
}

function buildMatrix(runs: Array<EvalRun>) {
  type Column = { key: string; runId: string; mode: string }
  type RowCell = Cell
  type CaseRow = { key: string; question: string; cells: Map<string, RowCell> }

  const columns: Array<Column> = []
  const caseMap = new Map<string, CaseRow>()

  for (const run of runs) {
    const modes = Array.from(new Set(run.results.map((r) => r.retrieval_mode)))
    for (const mode of modes) {
      const key = `${run.id}:${mode}`
      columns.push({ key, runId: run.id, mode })
    }
    for (const result of run.results) {
      const caseKey = result.eval_case_id ?? `${run.id}-${result.id}`
      let row = caseMap.get(caseKey)
      if (!row) {
        const question = String(
          result.eval_case_id
            ? result.eval_case_id
            : (findInlineQuestion(run, result.id) ?? caseKey),
        )
        row = { key: caseKey, question, cells: new Map() }
        caseMap.set(caseKey, row)
      }
      const metricValue =
        typeof result.metrics[PRIMARY_METRIC] === 'number'
          ? result.metrics[PRIMARY_METRIC]
          : null
      row.cells.set(`${run.id}:${result.retrieval_mode}`, {
        metricValue,
        answer: result.answer,
        traceId: result.trace_id,
        error: result.error,
      })
    }
  }

  const cases = Array.from(caseMap.values())

  const aggregates: Record<string, number | null> = {}
  for (const col of columns) {
    const values: Array<number> = []
    for (const row of cases) {
      const v = row.cells.get(col.key)?.metricValue
      if (v != null) values.push(v)
    }
    aggregates[col.key] =
      values.length > 0
        ? values.reduce((a, b) => a + b, 0) / values.length
        : null
  }

  return { columns, cases, aggregates }
}

function findInlineQuestion(
  run: EvalRun,
  _resultId: string,
): string | undefined {
  const cases = run.run_config['cases']
  if (Array.isArray(cases)) {
    const first = cases[0]
    if (first && typeof first === 'object' && 'question' in first) {
      return String((first as Record<string, unknown>).question ?? '')
    }
  }
  return undefined
}
