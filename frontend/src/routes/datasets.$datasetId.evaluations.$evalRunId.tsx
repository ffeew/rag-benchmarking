import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, Check, ExternalLink, Scale, X } from 'lucide-react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Skeleton } from '#/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '#/components/ui/table'
import { ErrorState } from '#/components/data/ErrorState'
import { MetricNumber } from '#/components/data/MetricNumber'
import { api } from '#/lib/api'
import { formatDateTime, formatDuration, formatPercent, truncateId } from '#/lib/format'
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
  const isRunning = !isTerminalJobStatus(run.status)
  const isPartial = run.status === 'failed' && run.results.length > 0
  const isRecomputed = run.metrics._recomputed === true

  type ModeMetrics = Record<string, unknown>
  const modes = Object.entries(run.metrics).filter(
    ([key, value]) =>
      typeof value === 'object' &&
      value !== null &&
      !Array.isArray(value) &&
      key !== 'ragas_run' &&
      // Bucket dicts for per-variant summaries are the ones that carry
      // ``case_count`` — anything else is a meta block (ingestion_diagnostics,
      // pairing_skew, etc.) we don't want to render as a variant card.
      typeof (value as Record<string, unknown>).case_count === 'number',
  ) as Array<[string, ModeMetrics]>

  function numericMetric(modeData: ModeMetrics, key: string): number | null {
    const v = modeData[key]
    return typeof v === 'number' ? v : null
  }

  function numericRunMetric(key: string): number | null {
    const v = (run.metrics as Record<string, unknown> | null | undefined)?.[key]
    return typeof v === 'number' ? v : null
  }

  function formatNumericMetric(value: number | null): string {
    if (value === null) return '—'
    if (value >= 0 && value <= 1) return formatPercent(value)
    return value.toFixed(2)
  }

  function formatMs(value: number | null): string {
    if (value === null) return '—'
    return formatDuration(value)
  }

  function formatUsd(value: number | null): string {
    if (value === null) return '—'
    return `$${value.toFixed(4)}`
  }

  function passLabel(passed: unknown): {
    label: string
    tone: 'ok' | 'bad' | 'neutral'
    icon: typeof Check | typeof X | null
  } {
    if (passed === true) return { label: 'PASS', tone: 'ok', icon: Check }
    if (passed === false) return { label: 'FAIL', tone: 'bad', icon: X }
    return { label: '—', tone: 'neutral', icon: null }
  }

  const passRate = numericRunMetric('pass_rate')
  const passCount = numericRunMetric('pass_count')
  const passEligibleCount = numericRunMetric('pass_eligible_count')
  const avgLatencyMs = numericRunMetric('avg_latency_ms')
  const totalCostUsd = numericRunMetric('total_cost_usd')
  // Mean across per-variant answer accuracy / mrr / recall so the headline
  // KPIs show a single overall number rather than picking an arbitrary variant.
  const variantAnswerAccuracies = modes
    .map(([, data]) => numericMetric(data, 'answer_accuracy_rate'))
    .filter((v): v is number => v !== null)
  const variantMrrs = modes
    .map(([, data]) => numericMetric(data, 'avg_mrr'))
    .filter((v): v is number => v !== null)
  const variantRecallAt5 = modes
    .map(([, data]) => numericMetric(data, 'avg_recall_at_5'))
    .filter((v): v is number => v !== null)
  function mean(values: number[]): number | null {
    if (values.length === 0) return null
    return values.reduce((a, b) => a + b, 0) / values.length
  }
  const headlineMetrics: Array<{ label: string; value: string }> = [
    {
      label: 'PASS RATE',
      value:
        passRate !== null
          ? `${formatPercent(passRate)}${
              passCount !== null && passEligibleCount !== null
                ? ` (${passCount}/${passEligibleCount})`
                : ''
            }`
          : '—',
    },
    { label: 'ANSWER ACCURACY', value: formatNumericMetric(mean(variantAnswerAccuracies)) },
    { label: 'RECALL@5', value: formatNumericMetric(mean(variantRecallAt5)) },
    { label: 'MRR', value: formatNumericMetric(mean(variantMrrs)) },
    { label: 'AVG LATENCY', value: formatMs(avgLatencyMs) },
    { label: 'TOTAL COST', value: formatUsd(totalCostUsd) },
  ]

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
              <Badge tone={isPartial ? toneForStatus('partial') : toneForStatus(run.status)}>
                {isPartial ? 'partial' : run.status}
              </Badge>
              {isPartial && (
                <span
                  className="text-[11px] text-[var(--ink-muted)] font-mono"
                  title="Job was reaped before reaching all cases. Metrics below are recomputed from the cases that did complete."
                >
                  {run.results.length} cases completed
                </span>
              )}
              {isRecomputed && !isPartial && (
                <Badge tone="outline" size="sm" title="Aggregate metrics were recomputed from per-case results">
                  recomputed
                </Badge>
              )}
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

      <section className="grid grid-cols-2 gap-px bg-[var(--rule)] border border-[var(--rule)] rounded-[5px] overflow-hidden md:grid-cols-3 lg:grid-cols-6">
        {headlineMetrics.map((m) => (
          <div key={m.label} className="bg-[var(--surface)] px-4 py-4">
            <MetricNumber label={m.label} value={m.value} size="md" />
          </div>
        ))}
      </section>

      {modes.length > 0 && (
        <section className="grid gap-4">
          {modes.map(([mode, modeData]) => (
            <Card key={mode}>
              <CardHeader
                title={
                  <span className="font-mono text-[12px] uppercase tracking-wide text-[var(--ink)]">
                    {mode.replace(/_/g, ' ')}
                  </span>
                }
              />
              <CardBody>
                <div className="grid gap-3">
                  <div>
                    <div className="mono-label text-[var(--ink-muted)] mb-2">
                      RETRIEVER
                    </div>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                      <MetricNumber
                        label="RECALL@5"
                        value={formatNumericMetric(numericMetric(modeData, 'avg_recall_at_5'))}
                        size="sm"
                      />
                      <MetricNumber
                        label="RECALL@10"
                        value={formatNumericMetric(numericMetric(modeData, 'avg_recall_at_10'))}
                        size="sm"
                      />
                      <MetricNumber
                        label="MRR"
                        value={formatNumericMetric(numericMetric(modeData, 'avg_mrr'))}
                        size="sm"
                      />
                      <MetricNumber
                        label="PAGE F1"
                        value={formatNumericMetric(numericMetric(modeData, 'avg_page_evidence_f1'))}
                        size="sm"
                      />
                      <MetricNumber
                        label="FILTER OK"
                        value={formatNumericMetric(numericMetric(modeData, 'metadata_filter_correctness_rate'))}
                        size="sm"
                      />
                    </div>
                  </div>
                  <div>
                    <div className="mono-label text-[var(--ink-muted)] mb-2">
                      CITATIONS
                    </div>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                      <MetricNumber
                        label="VALIDITY"
                        value={formatNumericMetric(numericMetric(modeData, 'citation_validity_rate'))}
                        size="sm"
                      />
                      <MetricNumber
                        label="COVERAGE"
                        value={formatNumericMetric(numericMetric(modeData, 'citation_coverage_rate'))}
                        size="sm"
                      />
                      <MetricNumber
                        label="PAGE HIT"
                        value={formatNumericMetric(numericMetric(modeData, 'citation_page_hit_rate'))}
                        size="sm"
                      />
                      <MetricNumber
                        label="INSUFFICIENT"
                        value={formatNumericMetric(numericMetric(modeData, 'insufficient_rate'))}
                        size="sm"
                      />
                    </div>
                  </div>
                  <div>
                    <div className="mono-label text-[var(--ink-muted)] mb-2">
                      COST &amp; LATENCY
                    </div>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                      <MetricNumber
                        label="AVG LATENCY"
                        value={formatMs(numericMetric(modeData, 'avg_latency_ms'))}
                        size="sm"
                      />
                      <MetricNumber
                        label="TOTAL TOKENS"
                        value={
                          numericMetric(modeData, 'total_tokens') === null
                            ? '—'
                            : (numericMetric(modeData, 'total_tokens') as number).toLocaleString()
                        }
                        size="sm"
                      />
                      <MetricNumber
                        label="TOTAL COST"
                        value={formatUsd(numericMetric(modeData, 'total_cost_usd'))}
                        size="sm"
                      />
                      <MetricNumber
                        label="COST / CASE"
                        value={formatUsd(numericMetric(modeData, 'cost_per_case_usd'))}
                        size="sm"
                      />
                    </div>
                  </div>
                </div>
              </CardBody>
            </Card>
          ))}
        </section>
      )}

      {run.errors.length > 0 && (
        <Card>
          <CardHeader
            title={
              <span>
                ERRORS{' '}
                <span className="font-mono numeric text-[var(--ink-muted)]">
                  {run.errors.length}
                </span>
              </span>
            }
          />
          <CardBody padded={false}>
            <Table>
              <THead>
                <tr>
                  <TH>CASE</TH>
                  <TH>VARIANT</TH>
                  <TH>CLASS</TH>
                  <TH>MESSAGE</TH>
                </tr>
              </THead>
              <TBody>
                {run.errors.map((err, idx) => {
                  const caseId =
                    typeof err.case_id === 'string' ? err.case_id : null
                  const variant =
                    typeof err.variant === 'string' ? err.variant : null
                  const errorClass =
                    typeof err.error_class === 'string' ? err.error_class : null
                  const message = typeof err.error === 'string' ? err.error : ''
                  return (
                    <TR key={idx}>
                      <TD className="font-mono text-[11px] text-[var(--ink-dim)]">
                        {caseId ? truncateId(caseId) : '—'}
                      </TD>
                      <TD className="font-mono text-[11px] text-[var(--ink-dim)]">
                        {variant ?? '—'}
                      </TD>
                      <TD className="font-mono text-[11px] text-[var(--bad)]">
                        {errorClass ?? '—'}
                      </TD>
                      <TD className="font-mono text-[11px] text-[var(--bad)] whitespace-pre-wrap break-words">
                        {message}
                      </TD>
                    </TR>
                  )
                })}
              </TBody>
            </Table>
          </CardBody>
        </Card>
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
                  <TH>PASS</TH>
                  <TH>ANSWER</TH>
                  <TH className="text-right">MRR</TH>
                  <TH className="text-right">RECALL@5</TH>
                  <TH className="text-right">CITATION</TH>
                  <TH className="text-right">LATENCY</TH>
                  <TH>TRACE</TH>
                </tr>
              </THead>
              <TBody>
                {run.results.map((r) => {
                  const m = r.metrics
                  const num = (k: string): number | null => {
                    const v = m[k]
                    return typeof v === 'number' ? v : null
                  }
                  const pass = passLabel(m.passed)
                  const Icon = pass.icon
                  return (
                    <TR key={r.id}>
                      <TD>
                        <Badge tone="cite" size="sm">
                          {r.retrieval_mode.replace('_', ' ')}
                        </Badge>
                      </TD>
                      <TD>
                        <Badge tone={pass.tone} size="sm">
                          {Icon ? <Icon className="h-3 w-3" /> : null}
                          {pass.label}
                        </Badge>
                      </TD>
                      <TD className="max-w-[420px]">
                        {r.error ? (
                          <span className="font-mono text-[var(--bad)]">{r.error}</span>
                        ) : (
                          <span className="text-[12px] text-[var(--ink)] leading-relaxed line-clamp-2">
                            {r.answer ?? '–'}
                          </span>
                        )}
                      </TD>
                      <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                        {formatNumericMetric(num('mrr'))}
                      </TD>
                      <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                        {formatNumericMetric(num('recall_at_5'))}
                      </TD>
                      <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                        {formatNumericMetric(num('citation_validity'))}
                      </TD>
                      <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                        {formatMs(num('latency_ms'))}
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
