import { useQueries, useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, Check, ExternalLink, Scale, X } from 'lucide-react'
import { useMemo } from 'react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Skeleton } from '#/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '#/components/ui/table'
import { ErrorState } from '#/components/data/ErrorState'
import { MetricNumber } from '#/components/data/MetricNumber'
import { api } from '#/lib/api'
import type {
  AblationPair,
  AblationReport,
  EvalCase,
  EvalResult,
} from '#/lib/api'
import {
  formatDateTime,
  formatDuration,
  formatPercent,
  truncateId,
} from '#/lib/format'
import { isTerminalJobStatus, nextJobInterval } from '#/lib/polling'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

// Metrics that only make sense when a retrieval phase actually ran. ``llm_only``
// skips retrieval entirely, so emitting 0% for these reads as a retriever
// failure rather than "this variant has no retrieval stage." Return null
// (rendered as ``—``) instead so the table communicates not-applicable.
const RETRIEVAL_ONLY_METRIC_KEYS = new Set([
  'avg_recall_at_5',
  'avg_recall_at_10',
  'avg_mrr',
  'avg_page_evidence_f1',
  'avg_chunk_evidence_f1',
  'avg_evidence_recall_at_5',
  'avg_evidence_recall_at_10',
  'avg_evidence_mrr',
  'avg_evidence_page_f1',
  'avg_evidence_chunk_f1',
  'metadata_filter_correctness_rate',
  // Per-result metric keys (used in the case-results table)
  'recall_at_5',
  'recall_at_10',
  'mrr',
  'page_evidence_f1',
  'chunk_evidence_f1',
])
// RAGAS metrics that require non-empty retrieved context. ``llm_only`` ships
// no context, so these are not applicable regardless of what RAGAS returns.
const CONTEXT_RAGAS_KEYS = new Set(['context_precision', 'context_recall'])

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

  // All hooks below run on every render (regardless of evalQuery state) so the
  // hook-call order stays stable — React forbids conditionally calling hooks.
  // Use ``evalQuery.data?.results ?? []`` so memo deps don't blow up during
  // loading/error renders before the eval payload arrives.
  const runResults = evalQuery.data?.results ?? []
  const referencedCaseIds = useMemo(
    () =>
      Array.from(
        new Set(
          runResults
            .map((r) => r.eval_case_id)
            .filter(
              (id): id is string => typeof id === 'string' && id.length > 0,
            ),
        ),
      ),
    [runResults],
  )
  const caseQueries = useQueries({
    queries: referencedCaseIds.map((id) => ({
      queryKey: qk.evalCases.detail(id),
      queryFn: () => api.evalCase(token, id),
      enabled: isAuthed,
      staleTime: 60_000,
    })),
  })
  const caseById = useMemo(() => {
    const m = new Map<string, EvalCase>()
    caseQueries.forEach((q, i) => {
      if (q.data) m.set(referencedCaseIds[i], q.data)
    })
    return m
  }, [caseQueries, referencedCaseIds])
  const groupedResults = useMemo(() => {
    const m = new Map<string, Array<EvalResult>>()
    for (const r of runResults) {
      const key = r.eval_case_id ?? '__unbound__'
      const bucket = m.get(key)
      if (bucket) {
        bucket.push(r)
      } else {
        m.set(key, [r])
      }
    }
    return Array.from(m.entries())
  }, [runResults])

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
      key !== 'ablation' &&
      // Bucket dicts for per-variant summaries are the ones that carry
      // ``case_count`` — anything else is a meta block (ingestion_diagnostics,
      // pairing_skew, ablation report, etc.) we don't want to render as a variant card.
      typeof (value as Record<string, unknown>).case_count === 'number',
  ) as Array<[string, ModeMetrics]>

  function numericMetric(modeData: ModeMetrics, key: string): number | null {
    const v = modeData[key]
    return typeof v === 'number' ? v : null
  }

  function isRetrievalCapable(
    retrievalMode: string | null | undefined,
  ): boolean {
    return retrievalMode !== 'llm_only'
  }

  function applicableMetric(modeData: ModeMetrics, key: string): number | null {
    const retrievalMode =
      typeof modeData.retrieval_mode === 'string'
        ? modeData.retrieval_mode
        : null
    if (
      !isRetrievalCapable(retrievalMode) &&
      RETRIEVAL_ONLY_METRIC_KEYS.has(key)
    ) {
      return null
    }
    return numericMetric(modeData, key)
  }

  function applicableRagasScore(
    modeData: ModeMetrics,
    key: string,
  ): number | null {
    const retrievalMode =
      typeof modeData.retrieval_mode === 'string'
        ? modeData.retrieval_mode
        : null
    if (!isRetrievalCapable(retrievalMode) && CONTEXT_RAGAS_KEYS.has(key)) {
      return null
    }
    return ragasScore(modeData, key)
  }

  function ragasScore(modeData: ModeMetrics, key: string): number | null {
    const diag = modeData.judge_diagnostics
    if (!diag || typeof diag !== 'object' || Array.isArray(diag)) return null
    const ragas = (diag as Record<string, unknown>).ragas
    if (!ragas || typeof ragas !== 'object' || Array.isArray(ragas)) return null
    const value = (ragas as Record<string, unknown>)[key]
    return typeof value === 'number' ? value : null
  }

  function ragasSkipReason(modeData: ModeMetrics): string | null {
    const diag = modeData.judge_diagnostics
    if (!diag || typeof diag !== 'object' || Array.isArray(diag)) return null
    const dict = diag as Record<string, unknown>
    const skipped = dict.ragas_skipped
    if (typeof skipped === 'string') return skipped
    const errored = dict.ragas_error
    if (typeof errored === 'string') return errored
    return null
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

  type AblationBlock =
    | { kind: 'report'; report: AblationReport }
    | {
        kind: 'skipped'
        reason: string
        baseline?: string
        variants?: Array<string>
      }
    | {
        kind: 'error'
        error: string
        baseline?: string
        variants?: Array<string>
      }
    | { kind: 'absent' }

  function readAblation(): AblationBlock {
    const raw = run.metrics.ablation
    if (!raw || typeof raw !== 'object' || Array.isArray(raw))
      return { kind: 'absent' }
    const dict = raw as Record<string, unknown>
    if (typeof dict.error === 'string') {
      return {
        kind: 'error',
        error: dict.error,
        baseline: typeof dict.baseline === 'string' ? dict.baseline : undefined,
        variants: Array.isArray(dict.variants)
          ? (dict.variants as Array<string>)
          : undefined,
      }
    }
    if (typeof dict.skipped === 'string') {
      return {
        kind: 'skipped',
        reason: dict.skipped,
        baseline: typeof dict.baseline === 'string' ? dict.baseline : undefined,
        variants: Array.isArray(dict.variants)
          ? (dict.variants as Array<string>)
          : undefined,
      }
    }
    if (Array.isArray(dict.pair_results) && typeof dict.baseline === 'string') {
      return { kind: 'report', report: raw as unknown as AblationReport }
    }
    return { kind: 'absent' }
  }

  function formatPair(value: number | null | undefined, digits = 3): string {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
    return value.toFixed(digits)
  }

  function formatSignedDiff(
    value: number | null | undefined,
    digits = 3,
  ): string {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
    const sign = value > 0 ? '+' : ''
    return `${sign}${value.toFixed(digits)}`
  }

  const ablation = readAblation()

  const passRate = numericRunMetric('pass_rate')
  const passCount = numericRunMetric('pass_count')
  const passEligibleCount = numericRunMetric('pass_eligible_count')
  const avgLatencyMs = numericRunMetric('avg_latency_ms')
  const totalCostUsd = numericRunMetric('total_cost_usd')
  // The headline strip only shows variant-agnostic rollups. Per-variant numbers
  // (answer accuracy, recall, MRR) live in the variant cards below and in the
  // ``VARIANT COMPARISON`` matrix so we don't average e.g. ``single_pass=100%``
  // and ``llm_only=0%`` into a meaningless ``50%`` headline tile.
  const distinctCaseCount = new Set(
    run.results.map((r) => r.eval_case_id).filter(Boolean),
  ).size
  const variantCount = modes.length
  const totalTokens = modes.reduce<number | null>((sum, [, data]) => {
    const v = numericMetric(data, 'total_tokens')
    if (v === null) return sum
    return (sum ?? 0) + v
  }, null)
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
    {
      label: 'CASES',
      value: distinctCaseCount > 0 ? String(distinctCaseCount) : '—',
    },
    { label: 'VARIANTS', value: variantCount > 0 ? String(variantCount) : '—' },
    { label: 'AVG LATENCY', value: formatMs(avgLatencyMs) },
    { label: 'TOTAL COST', value: formatUsd(totalCostUsd) },
    {
      label: 'TOTAL TOKENS',
      value: totalTokens === null ? '—' : totalTokens.toLocaleString(),
    },
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
              <Badge
                tone={
                  isPartial
                    ? toneForStatus('partial')
                    : toneForStatus(run.status)
                }
              >
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
                <Badge
                  tone="outline"
                  size="sm"
                  title="Aggregate metrics were recomputed from per-case results"
                >
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

      {modes.length > 1 && (
        <Card>
          <CardHeader
            title={
              <span className="font-mono text-[12px] uppercase tracking-wide text-[var(--ink)]">
                VARIANT COMPARISON
              </span>
            }
          />
          <CardBody padded={false}>
            <Table>
              <THead>
                <tr>
                  <TH>VARIANT</TH>
                  <TH className="text-right">PASS RATE</TH>
                  <TH className="text-right">ANSWER ACC</TH>
                  <TH className="text-right">RECALL@5</TH>
                  <TH className="text-right">MRR</TH>
                  <TH className="text-right">CITATION VALIDITY</TH>
                  <TH className="text-right">AVG LATENCY</TH>
                  <TH className="text-right">COST / CASE</TH>
                </tr>
              </THead>
              <TBody>
                {modes.map(([mode, data]) => (
                  <TR key={mode}>
                    <TD>
                      <Badge tone="cite" size="sm">
                        {mode.replace(/_/g, ' ')}
                      </Badge>
                    </TD>
                    <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                      {formatNumericMetric(numericMetric(data, 'pass_rate'))}
                    </TD>
                    <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                      {formatNumericMetric(
                        numericMetric(data, 'answer_accuracy_rate'),
                      )}
                    </TD>
                    <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                      {formatNumericMetric(
                        applicableMetric(data, 'avg_recall_at_5'),
                      )}
                    </TD>
                    <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                      {formatNumericMetric(applicableMetric(data, 'avg_mrr'))}
                    </TD>
                    <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                      {formatNumericMetric(
                        numericMetric(data, 'citation_validity_rate'),
                      )}
                    </TD>
                    <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                      {formatMs(numericMetric(data, 'avg_latency_ms'))}
                    </TD>
                    <TD className="text-right font-mono numeric text-[11px] text-[var(--ink)]">
                      {formatUsd(numericMetric(data, 'cost_per_case_usd'))}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardBody>
        </Card>
      )}

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
                  {isRetrievalCapable(
                    typeof modeData.retrieval_mode === 'string'
                      ? modeData.retrieval_mode
                      : null,
                  ) ? (
                    <div>
                      <div className="mono-label text-[var(--ink-muted)] mb-2">
                        RETRIEVER
                      </div>
                      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
                        <MetricNumber
                          label="RECALL@5"
                          value={formatNumericMetric(
                            applicableMetric(modeData, 'avg_recall_at_5'),
                          )}
                          size="sm"
                        />
                        <MetricNumber
                          label="RECALL@10"
                          value={formatNumericMetric(
                            applicableMetric(modeData, 'avg_recall_at_10'),
                          )}
                          size="sm"
                        />
                        <MetricNumber
                          label="MRR"
                          value={formatNumericMetric(
                            applicableMetric(modeData, 'avg_mrr'),
                          )}
                          size="sm"
                        />
                        <MetricNumber
                          label="PAGE F1"
                          value={formatNumericMetric(
                            applicableMetric(modeData, 'avg_page_evidence_f1'),
                          )}
                          size="sm"
                        />
                        <MetricNumber
                          label="CHUNK F1"
                          value={formatNumericMetric(
                            applicableMetric(modeData, 'avg_chunk_evidence_f1'),
                          )}
                          size="sm"
                        />
                        <MetricNumber
                          label="FILTER OK"
                          value={formatNumericMetric(
                            applicableMetric(
                              modeData,
                              'metadata_filter_correctness_rate',
                            ),
                          )}
                          size="sm"
                        />
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="mono-label text-[var(--ink-muted)] mb-2 flex items-center gap-2">
                        <span>RETRIEVER</span>
                        <Badge tone="outline" size="sm">
                          no retrieval stage
                        </Badge>
                      </div>
                      <p className="text-[11.5px] text-[var(--ink-muted)] font-mono">
                        This variant answers directly from the model with no
                        retrieval. Retrieval metrics (recall, MRR, page/chunk
                        F1, filter correctness) are not applicable.
                      </p>
                    </div>
                  )}
                  <div>
                    <div className="mono-label text-[var(--ink-muted)] mb-2 flex items-center gap-2">
                      <span>GENERATOR</span>
                      {ragasSkipReason(modeData) !== null && (
                        <Badge tone="warn" size="sm">
                          RAGAS {ragasSkipReason(modeData)}
                        </Badge>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                      <MetricNumber
                        label="ANSWER ACC"
                        value={formatNumericMetric(
                          numericMetric(modeData, 'answer_accuracy_rate'),
                        )}
                        size="sm"
                      />
                      <MetricNumber
                        label="FAITHFULNESS"
                        value={formatNumericMetric(
                          ragasScore(modeData, 'faithfulness'),
                        )}
                        size="sm"
                      />
                      <MetricNumber
                        label="CTX PRECISION"
                        value={formatNumericMetric(
                          applicableRagasScore(modeData, 'context_precision'),
                        )}
                        size="sm"
                      />
                      <MetricNumber
                        label="CTX RECALL"
                        value={formatNumericMetric(
                          applicableRagasScore(modeData, 'context_recall'),
                        )}
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
                        value={formatNumericMetric(
                          numericMetric(modeData, 'citation_validity_rate'),
                        )}
                        size="sm"
                      />
                      <MetricNumber
                        label="COVERAGE"
                        value={formatNumericMetric(
                          numericMetric(modeData, 'citation_coverage_rate'),
                        )}
                        size="sm"
                      />
                      <MetricNumber
                        label="PAGE HIT"
                        value={formatNumericMetric(
                          numericMetric(modeData, 'citation_page_hit_rate'),
                        )}
                        size="sm"
                      />
                      <MetricNumber
                        label="INSUFFICIENT"
                        value={formatNumericMetric(
                          numericMetric(modeData, 'insufficient_rate'),
                        )}
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
                        value={formatMs(
                          numericMetric(modeData, 'avg_latency_ms'),
                        )}
                        size="sm"
                      />
                      <MetricNumber
                        label="TOTAL TOKENS"
                        value={
                          numericMetric(modeData, 'total_tokens') === null
                            ? '—'
                            : (
                                numericMetric(
                                  modeData,
                                  'total_tokens',
                                ) as number
                              ).toLocaleString()
                        }
                        size="sm"
                      />
                      <MetricNumber
                        label="TOTAL COST"
                        value={formatUsd(
                          numericMetric(modeData, 'total_cost_usd'),
                        )}
                        size="sm"
                      />
                      <MetricNumber
                        label="COST / CASE"
                        value={formatUsd(
                          numericMetric(modeData, 'cost_per_case_usd'),
                        )}
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

      {ablation.kind !== 'absent' && (
        <Card>
          <CardHeader
            title={
              <span className="font-mono text-[12px] uppercase tracking-wide text-[var(--ink)]">
                ABLATION (paired)
              </span>
            }
          />
          <CardBody padded={ablation.kind !== 'report'}>
            {ablation.kind === 'skipped' && (
              <div className="text-[12px] text-[var(--ink-muted)] font-mono">
                Skipped: {ablation.reason}
                {ablation.variants && ablation.variants.length > 0
                  ? ` (variants: ${ablation.variants.join(', ')})`
                  : ''}
              </div>
            )}
            {ablation.kind === 'error' && (
              <div className="text-[12px] text-[var(--bad)] font-mono">
                Error: {ablation.error}
              </div>
            )}
            {ablation.kind === 'report' && (
              <AblationPivotTable report={ablation.report} />
            )}
          </CardBody>
        </Card>
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

      <section className="grid gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="font-mono text-[12px] uppercase tracking-wide text-[var(--ink)]">
            CASE RESULTS{' '}
            <span className="text-[var(--ink-muted)]">
              {groupedResults.length} case
              {groupedResults.length === 1 ? '' : 's'} · {run.results.length}{' '}
              result{run.results.length === 1 ? '' : 's'}
            </span>
          </h2>
          {isRunning && (
            <Badge tone="warn" size="sm">
              streaming
            </Badge>
          )}
        </div>
        {run.results.length === 0 ? (
          <Card>
            <CardBody>
              <p className="text-center text-[12.5px] text-[var(--ink-muted)]">
                No results yet.
              </p>
            </CardBody>
          </Card>
        ) : (
          groupedResults.map(([caseId, results]) => {
            const evalCase =
              caseId === '__unbound__' ? null : caseById.get(caseId)
            return (
              <CaseResultGroup
                key={caseId}
                caseId={caseId}
                evalCase={evalCase}
                results={results}
                formatNumericMetric={formatNumericMetric}
                formatMs={formatMs}
                passLabel={passLabel}
                isRetrievalCapable={isRetrievalCapable}
              />
            )
          })
        )}
      </section>
    </div>
  )
}

// Paper-style ablation table: rows = systems (baseline first), columns =
// metrics. Each variant cell stacks the mean on top of the signed diff vs.
// baseline plus significance stars (FDR-corrected q for primary endpoints,
// raw p for secondary).
function AblationPivotTable({ report }: { report: AblationReport }) {
  const baseline = report.baseline
  const treatments = report.variants.filter((v) => v !== baseline)
  const allRows = [baseline, ...treatments]

  // Primary endpoints first, then secondary, then any extras present in
  // pair_results that didn't make either list.
  const orderedMetrics: Array<string> = []
  const seenMetrics = new Set<string>()
  for (const m of [
    ...report.primary_endpoints,
    ...report.secondary_endpoints,
  ]) {
    if (!seenMetrics.has(m)) {
      seenMetrics.add(m)
      orderedMetrics.push(m)
    }
  }
  for (const pair of report.pair_results) {
    if (!seenMetrics.has(pair.metric)) {
      seenMetrics.add(pair.metric)
      orderedMetrics.push(pair.metric)
    }
  }

  const primarySet = new Set(report.primary_endpoints)

  // (variant, metric) → pair
  const pairByKey = new Map<string, AblationPair>()
  // metric → mean_baseline (any pair for that metric carries the value).
  const baselineMean = new Map<string, number>()
  for (const pair of report.pair_results) {
    pairByKey.set(`${pair.treatment}|${pair.metric}`, pair)
    if (!baselineMean.has(pair.metric)) {
      baselineMean.set(pair.metric, pair.mean_baseline)
    }
  }

  return (
    <>
      <div className="px-4 pt-4 pb-2 text-[12px] text-[var(--ink-muted)] font-mono">
        baseline <span className="text-[var(--ink)]">{baseline}</span> ·{' '}
        {treatments.length} variant{treatments.length === 1 ? '' : 's'} ·{' '}
        {report.case_count} paired cases
      </div>
      <div className="px-4 pb-3 text-[11px] text-[var(--ink-muted)] font-mono leading-relaxed">
        Rows are systems, columns are metrics. The baseline row shows the mean;
        each variant cell shows the mean (top) with the signed difference vs.{' '}
        <span className="text-[var(--ink)]">{baseline}</span> below.
        Significance:
        <span className="ml-1 text-[var(--ink)]">*** p &lt; .001</span>,
        <span className="ml-1 text-[var(--ink)]">** p &lt; .01</span>,
        <span className="ml-1 text-[var(--ink)]">* p &lt; .05</span> — primary
        metrics use FDR-corrected q, secondary use raw p. Arrow in the header
        marks the desired direction (↑ higher is better, ↓ lower is better).
      </div>
      <div>
        <Table>
          <THead>
            <tr>
              <TH>SYSTEM</TH>
              {orderedMetrics.map((metric) => (
                <TH
                  key={metric}
                  className="text-right whitespace-nowrap"
                  title={
                    primarySet.has(metric)
                      ? 'primary endpoint'
                      : 'secondary endpoint'
                  }
                >
                  <span
                    className={
                      primarySet.has(metric)
                        ? 'text-[var(--ink)]'
                        : 'text-[var(--ink-muted)]'
                    }
                  >
                    {metricHeaderLabel(metric)}
                  </span>
                </TH>
              ))}
            </tr>
          </THead>
          <TBody>
            {allRows.map((variant) => {
              const isBaseline = variant === baseline
              return (
                <TR key={variant}>
                  <TD>
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge tone="cite" size="sm">
                        {variant.replace(/_/g, ' ')}
                      </Badge>
                      {isBaseline && (
                        <span className="font-mono text-[10px] uppercase tracking-wide text-[var(--ink-muted)]">
                          baseline
                        </span>
                      )}
                    </div>
                  </TD>
                  {orderedMetrics.map((metric) => (
                    <TD
                      key={metric}
                      className="text-right whitespace-nowrap align-top"
                    >
                      <AblationCell
                        isBaseline={isBaseline}
                        metric={metric}
                        variant={variant}
                        pair={pairByKey.get(`${variant}|${metric}`)}
                        baselineMean={baselineMean.get(metric) ?? null}
                        useQValue={primarySet.has(metric)}
                      />
                    </TD>
                  ))}
                </TR>
              )
            })}
          </TBody>
        </Table>
      </div>
    </>
  )
}

function AblationCell({
  isBaseline,
  metric,
  variant,
  pair,
  baselineMean,
  useQValue,
}: {
  isBaseline: boolean
  metric: string
  variant: string
  pair: AblationPair | undefined
  baselineMean: number | null
  useQValue: boolean
}) {
  if (isBaseline) {
    if (baselineMean === null) {
      return <span className="text-[var(--ink-muted)]">—</span>
    }
    return (
      <div className="font-mono numeric text-[11px] text-[var(--ink)]">
        {formatMetricCellValue(metric, baselineMean)}
      </div>
    )
  }
  if (!pair) {
    return <span className="text-[var(--ink-muted)]">—</span>
  }
  if (!isAblationMetricApplicable(metric, variant)) {
    return (
      <span className="font-mono text-[10px] text-[var(--ink-muted)]">N/A</span>
    )
  }
  const diff = pair.mean_treatment - pair.mean_baseline
  const stars = significanceStars(useQValue ? pair.q_value : pair.p_value)
  return (
    <div className="leading-tight">
      <div className="font-mono numeric text-[11px] text-[var(--ink)]">
        {formatMetricCellValue(metric, pair.mean_treatment)}
      </div>
      <div className="font-mono numeric text-[10px] text-[var(--ink-muted)]">
        {formatMetricCellDiff(metric, diff)}
        {stars && <span className="ml-0.5 text-[var(--ink)]">{stars}</span>}
      </div>
    </div>
  )
}

// Metrics that don't apply when a variant doesn't run a retrieval stage.
const ABLATION_RETRIEVAL_ONLY = new Set([
  'recall_at_5',
  'recall_at_10',
  'strict_recall_at_10',
  'mrr',
  'strict_mrr',
  'page_evidence_f1',
  'chunk_evidence_f1',
  'metadata_filter_correctness',
])

function isAblationMetricApplicable(metric: string, variant: string): boolean {
  if (variant === 'llm_only' && ABLATION_RETRIEVAL_ONLY.has(metric)) {
    return false
  }
  return true
}

function significanceStars(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return ''
  if (p < 0.001) return '***'
  if (p < 0.01) return '**'
  if (p < 0.05) return '*'
  return ''
}

const METRIC_HEADERS: Record<string, string> = {
  answer_accuracy: 'ANSWER ACC ↑',
  expected_contains: 'CONTAINS ↑',
  strict_recall_at_10: 'STRICT R@10 ↑',
  recall_at_5: 'R@5 ↑',
  recall_at_10: 'R@10 ↑',
  mrr: 'MRR ↑',
  strict_mrr: 'STRICT MRR ↑',
  page_evidence_f1: 'PAGE F1 ↑',
  chunk_evidence_f1: 'CHUNK F1 ↑',
  citation_validity: 'CITE VALID ↑',
  citation_coverage: 'CITE COV ↑',
  citation_gold_precision: 'CITE GOLD P ↑',
  citation_gold_recall: 'CITE GOLD R ↑',
  metadata_filter_correctness: 'FILTER OK ↑',
  latency_ms: 'LATENCY ↓',
  cost_usd: 'COST ↓',
}

function metricHeaderLabel(metric: string): string {
  return METRIC_HEADERS[metric] ?? metric.toUpperCase().replace(/_/g, ' ')
}

function formatMetricCellValue(metric: string, value: number): string {
  if (!Number.isFinite(value)) return '—'
  if (metric === 'latency_ms') return `${(value / 1000).toFixed(1)}s`
  if (metric === 'cost_usd') return `$${value.toFixed(4)}`
  return value.toFixed(3)
}

function formatMetricCellDiff(metric: string, diff: number): string {
  if (!Number.isFinite(diff)) return '—'
  const sign = diff > 0 ? '+' : ''
  if (metric === 'latency_ms') return `${sign}${(diff / 1000).toFixed(1)}s`
  if (metric === 'cost_usd') return `${sign}$${diff.toFixed(4)}`
  return `${sign}${diff.toFixed(3)}`
}

// One card per eval case, with the case metadata (key/question/expected
// answer/gold pages) above a per-variant results table. Grouping by case
// makes it obvious which question every row is answering and lets the
// operator scan all variants for a single case side-by-side.
function CaseResultGroup({
  caseId,
  evalCase,
  results,
  formatNumericMetric,
  formatMs,
  passLabel,
  isRetrievalCapable,
}: {
  caseId: string
  evalCase: EvalCase | null | undefined
  results: Array<EvalResult>
  formatNumericMetric: (value: number | null) => string
  formatMs: (value: number | null) => string
  passLabel: (passed: unknown) => {
    label: string
    tone: 'ok' | 'bad' | 'neutral'
    icon: typeof Check | typeof X | null
  }
  isRetrievalCapable: (retrievalMode: string | null | undefined) => boolean
}) {
  const isUnbound = caseId === '__unbound__'
  const expectedSummary = evalCase ? summarizeExpected(evalCase) : null
  const goldPages = evalCase ? summarizeGoldEvidence(evalCase) : null
  const passed = results.filter((r) => r.metrics.passed === true).length

  return (
    <Card>
      <CardHeader
        title={
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-[11px] uppercase tracking-wide text-[var(--ink-muted)]">
                CASE
              </span>
              {evalCase?.case_key ? (
                <span className="font-mono text-[12px] text-[var(--ink)]">
                  {evalCase.case_key}
                </span>
              ) : (
                <span className="font-mono text-[12px] text-[var(--ink-muted)]">
                  {isUnbound ? '(unbound result row)' : truncateId(caseId)}
                </span>
              )}
              {evalCase?.verification_status && (
                <Badge
                  tone={
                    evalCase.verification_status === 'verified'
                      ? 'ok'
                      : 'outline'
                  }
                  size="sm"
                >
                  {evalCase.verification_status}
                </Badge>
              )}
              {(evalCase?.tags ?? []).slice(0, 4).map((tag) => (
                <Badge key={tag} tone="outline" size="sm">
                  {tag}
                </Badge>
              ))}
            </div>
            {evalCase?.question && (
              <p className="text-[12.5px] text-[var(--ink)] leading-relaxed">
                {evalCase.question}
              </p>
            )}
          </div>
        }
        actions={
          <span className="font-mono text-[11px] text-[var(--ink-muted)]">
            {passed}/{results.length} passed
          </span>
        }
      />
      <CardBody padded={false}>
        {(expectedSummary || goldPages) && (
          <div className="grid gap-1 px-4 pt-3 pb-3 border-b border-[var(--rule)]">
            {expectedSummary && (
              <div className="text-[11.5px] font-mono leading-relaxed">
                <span className="text-[var(--ink-muted)] mr-2">EXPECTED</span>
                <span className="text-[var(--ink)]">{expectedSummary}</span>
              </div>
            )}
            {goldPages && (
              <div className="text-[11.5px] font-mono leading-relaxed">
                <span className="text-[var(--ink-muted)] mr-2">
                  GOLD EVIDENCE
                </span>
                <span className="text-[var(--ink)]">{goldPages}</span>
              </div>
            )}
          </div>
        )}
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
            {results.map((r) => {
              const m = r.metrics
              const retrievalCapable = isRetrievalCapable(r.retrieval_mode)
              const num = (k: string): number | null => {
                if (!retrievalCapable && RETRIEVAL_ONLY_METRIC_KEYS.has(k)) {
                  return null
                }
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
                      <span className="font-mono text-[var(--bad)]">
                        {r.error}
                      </span>
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
      </CardBody>
    </Card>
  )
}

// Render a short string describing the case's expected answer. Prefers the
// structured ``expected_answer_spec`` (numeric values, required claims) and
// falls back to the free-text ``expected_answer`` so the case header is
// informative even for cases without a structured spec.
function summarizeExpected(evalCase: EvalCase): string | null {
  const spec = evalCase.expected_answer_spec
  const parts: Array<string> = []
  for (const ev of spec.expected_values) {
    if (typeof ev !== 'object') continue
    const obj = ev as Record<string, unknown>
    const label = typeof obj.label === 'string' ? obj.label : null
    const numericRaw = obj.value_numeric
    const numeric =
      typeof numericRaw === 'number' && Number.isFinite(numericRaw)
        ? numericRaw
        : null
    const unit = typeof obj.unit === 'string' ? obj.unit : null
    const text = typeof obj.value_text === 'string' ? obj.value_text : null
    const piece =
      numeric !== null
        ? `${label ? `${label} = ` : ''}${numeric.toLocaleString()}${unit ? ` ${unit}` : ''}`
        : text
          ? `${label ? `${label} = ` : ''}${text}`
          : null
    if (piece) parts.push(piece)
  }
  for (const claim of spec.required_claims) {
    if (typeof claim === 'string') parts.push(`“${claim}”`)
  }
  if (parts.length > 0) return parts.join('; ')
  if (evalCase.expected_answer) return evalCase.expected_answer
  return null
}

function summarizeGoldEvidence(evalCase: EvalCase): string | null {
  const entries = evalCase.expected_evidence
  if (entries.length === 0) return null
  const formatted = entries.slice(0, 4).map((e) => {
    const ticker = e.ticker ?? null
    const form = e.form_type ?? null
    const date = e.filing_date ?? null
    const page = e.page_number ?? null
    const head = [ticker, date, form].filter(Boolean).join(' ')
    return `${head}${head ? ', ' : ''}p. ${page ?? '?'}`
  })
  const more =
    entries.length > formatted.length
      ? ` (+${entries.length - formatted.length} more)`
      : ''
  return `${formatted.join(' · ')}${more}`
}
