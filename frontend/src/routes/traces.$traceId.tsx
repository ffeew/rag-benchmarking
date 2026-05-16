import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate, Link } from '@tanstack/react-router'
import { ArrowLeft, Copy, ExternalLink, Repeat, Sparkles } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Skeleton } from '#/components/ui/skeleton'
import { AnswerArticle } from '#/components/query/AnswerArticle'
import { CitationCard } from '#/components/query/CitationCard'
import { ConfidenceMeter } from '#/components/query/ConfidenceMeter'
import { ErrorState } from '#/components/data/ErrorState'
import { ModelMetaCard } from '#/components/trace/ModelMetaCard'
import { PlanCard } from '#/components/trace/PlanCard'
import { RetrievalCallCard } from '#/components/trace/RetrievalCallCard'
import { TimingBar } from '#/components/trace/TimingBar'
import { VerifierVerdict } from '#/components/trace/VerifierVerdict'
import { api } from '#/lib/api'
import { formatDateTime, truncateId } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { toast } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/traces/$traceId')({
  component: TracePage,
})

function TracePage() {
  const { traceId } = Route.useParams()
  const { token, isAuthed } = useToken()
  const navigate = useNavigate()
  const [highlighted, setHighlighted] = useState<number | null>(null)

  const traceQuery = useQuery({
    queryKey: qk.traces.detail(traceId),
    queryFn: () => api.trace(token, traceId),
    enabled: isAuthed,
  })

  if (traceQuery.isLoading) {
    return (
      <div className="p-6 grid gap-3">
        <Skeleton className="h-6 w-72" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (traceQuery.isError || !traceQuery.data) {
    return (
      <ErrorState
        title="Trace not found"
        error={traceQuery.error}
        onRetry={() => traceQuery.refetch()}
      />
    )
  }

  const trace = traceQuery.data

  function reproduce() {
    try {
      window.sessionStorage.setItem(
        'rag.queryDraft',
        JSON.stringify({
          question: trace.user_question,
          retrieval_mode: trace.retrieval_mode,
          dataset_id: trace.dataset_id,
        }),
      )
    } catch {
      /* ignore */
    }
    toast.info('Question copied — opening query workspace')
    void navigate(paths.query)
  }

  function copyId() {
    try {
      void navigator.clipboard.writeText(trace.id)
      toast.success('Trace ID copied')
    } catch {
      toast.error('Copy failed')
    }
  }

  function jumpToCitation(idx: number) {
    setHighlighted(idx)
    const node = document.getElementById(`citation-${idx}`)
    if (node) node.scrollIntoView({ behavior: 'smooth', block: 'center' })
    window.setTimeout(
      () => setHighlighted((current) => (current === idx ? null : current)),
      1400,
    )
  }

  const rawConfidence = (trace.verifier_result as { confidence?: unknown })
    .confidence
  const confidence =
    typeof rawConfidence === 'number' && Number.isFinite(rawConfidence)
      ? rawConfidence
      : null

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6 grid gap-5">
      {/* Header */}
      <div>
        <Button
          variant="ghost"
          size="xs"
          asChild
          leading={<ArrowLeft className="h-3 w-3" />}
        >
          <Link {...paths.traces}>back to traces</Link>
        </Button>
        <div className="mt-2 flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="mono-label text-[var(--ink-muted)]">TRACE</div>
            <h1 className="mt-1 text-[20px] leading-snug font-semibold tracking-tight">
              {trace.user_question}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11.5px]">
              <Badge tone="cite" size="md">
                {trace.retrieval_mode.replace('_', ' ')}
              </Badge>
              <button
                type="button"
                onClick={copyId}
                className="inline-flex items-center gap-1 rounded-[2px] border border-[var(--rule)] bg-[var(--surface-2)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--ink-dim)] hover:bg-[var(--surface-3)]"
              >
                {truncateId(trace.id, 8, 6)}
                <Copy className="h-2.5 w-2.5" />
              </button>
              <span className="font-mono text-[10.5px] text-[var(--ink-muted)]">
                {formatDateTime(trace.created_at)}
              </span>
              <Link
                {...paths.dataset(trace.dataset_id)}
                className="inline-flex items-center gap-1 font-mono text-[10.5px] text-[var(--accent)] hover:underline"
              >
                dataset <ExternalLink className="h-2.5 w-2.5" />
              </Link>
            </div>
          </div>
          <Button
            onClick={reproduce}
            leading={<Repeat className="h-3.5 w-3.5" />}
          >
            Reproduce
          </Button>
        </div>
      </div>

      {/* Answer */}
      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <Sparkles className="h-3.5 w-3.5 text-[var(--accent)]" />
              ANSWER
            </span>
          }
          actions={
            confidence !== null ? <ConfidenceMeter value={confidence} /> : null
          }
        />
        <CardBody>
          {trace.answer ? (
            <AnswerArticle
              answer={trace.answer}
              highlightCitation={highlighted}
              onCitationClick={jumpToCitation}
            />
          ) : (
            <p className="text-[12.5px] text-[var(--ink-muted)]">
              No answer recorded for this trace.
            </p>
          )}
        </CardBody>
      </Card>

      {/* Timing */}
      <Card>
        <CardBody>
          <TimingBar timings={trace.timings} />
        </CardBody>
      </Card>

      {/* Plan + Verifier + Calls + Evidence */}
      <div className="grid gap-5 lg:grid-cols-[2fr_3fr]">
        <div className="grid gap-5 self-start lg:sticky lg:top-4">
          <PlanCard plan={trace.plan} />
          <VerifierVerdict verdict={trace.verifier_result} />
          <ModelMetaCard
            modelMetadata={trace.model_metadata}
            finalAnswerMetadata={trace.final_answer_metadata}
          />
        </div>

        <div className="grid gap-5 min-w-0">
          <Card>
            <CardHeader
              title={
                <span>
                  RETRIEVAL CALLS{' '}
                  <span className="text-[var(--ink-muted)] font-mono numeric">
                    {trace.retrieval_calls.length}
                  </span>
                </span>
              }
            />
            <CardBody className="grid gap-3">
              {trace.retrieval_calls.length === 0 ? (
                <p className="text-[12.5px] text-[var(--ink-muted)]">
                  No retrieval calls recorded (LLM-only mode?).
                </p>
              ) : (
                trace.retrieval_calls.map((call, i) => (
                  <RetrievalCallCard key={i} call={call} index={i} />
                ))
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title={
                <span>
                  CITATIONS{' '}
                  <span className="text-[var(--ink-muted)] font-mono numeric">
                    {trace.citations.length}
                  </span>
                </span>
              }
            />
            <CardBody className="grid gap-2">
              {trace.citations.length === 0 ? (
                <p className="text-[12.5px] text-[var(--ink-muted)]">
                  No citations.
                </p>
              ) : (
                trace.citations.map((c, i) => (
                  <CitationCard
                    key={c.chunk_id}
                    citation={c}
                    index={i + 1}
                    highlighted={highlighted === i + 1}
                    onSelect={(idx) => jumpToCitation(idx)}
                  />
                ))
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  )
}
