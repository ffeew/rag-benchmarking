import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import {
  AlertTriangle,
  ArrowRight,
  Cog,
  CornerDownLeft,
  Filter,
  RotateCcw,
  Search,
  Sparkles,
} from 'lucide-react'
import { useMemo, useRef, useState } from 'react'

import { Badge } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '#/components/ui/collapsible'
import { Field } from '#/components/ui/field'
import { Input, Textarea } from '#/components/ui/input'
import { Kbd } from '#/components/ui/kbd'
import { Skeleton } from '#/components/ui/skeleton'
import { Slider } from '#/components/ui/slider'
import { Switch } from '#/components/ui/switch'
import { Chip } from '#/components/data/Chip'
import { EmptyState } from '#/components/data/EmptyState'
import { AnswerArticle } from '#/components/query/AnswerArticle'
import { CitationCard } from '#/components/query/CitationCard'
import { ConfidenceMeter } from '#/components/query/ConfidenceMeter'
import { EvidenceList } from '#/components/query/EvidenceList'
import { RetrievalModeSelect } from '#/components/query/RetrievalModeSelect'
import { api } from '#/lib/api'
import type { QueryResponse, RetrievalMode } from '#/lib/api'
import { formatDuration } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { toast, toastApiError } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

const EXAMPLE_QUESTIONS = [
  "What was Microsoft's total revenue in FY2024?",
  "What is Tesla's current long-term debt as reported in their latest 10-K?",
  "Break down Amazon's revenue by segment for the last reported fiscal year.",
  "How has Apple's gross margin trended over the past 3 fiscal years?",
  'Give me an overview of the recent performance of Nvidia.',
]

const HISTORY_KEY = 'rag.queryHistory'

type HistoryEntry = { question: string; ts: number }

function readHistory(): Array<HistoryEntry> {
  try {
    const v = window.localStorage.getItem(HISTORY_KEY)
    if (!v) return []
    return (JSON.parse(v) as Array<HistoryEntry>).slice(0, 12)
  } catch {
    return []
  }
}
function writeHistory(entry: HistoryEntry) {
  try {
    const existing = readHistory().filter((e) => e.question !== entry.question)
    const next = [entry, ...existing].slice(0, 12)
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  } catch {
    /* ignore */
  }
}

export const Route = createFileRoute('/datasets/$datasetId/query')({
  component: QueryWorkspace,
})

function QueryWorkspace() {
  const { datasetId } = Route.useParams()
  const { token } = useToken()
  const queryClient = useQueryClient()

  // Stop-gap: pull up to 200 docs to populate the filter chips.
  const docsQuery = useQuery({
    queryKey: qk.datasets.documents({ datasetId, limit: 200, offset: 0 }),
    queryFn: () => api.documents(token, datasetId, { limit: 200 }),
    staleTime: 60_000,
  })
  const docs = docsQuery.data?.items ?? []
  const allTickers = useMemo(
    () => Array.from(new Set(docs.map((d) => d.ticker))).sort(),
    [docs],
  )
  const allForms = useMemo(
    () => Array.from(new Set(docs.map((d) => d.form_type))).sort(),
    [docs],
  )

  const placeholder = useMemo(
    () =>
      EXAMPLE_QUESTIONS[Math.floor(Math.random() * EXAMPLE_QUESTIONS.length)],
    [],
  )

  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState<RetrievalMode>('full_agentic')
  const [tickers, setTickers] = useState<Array<string>>([])
  const [forms, setForms] = useState<Array<string>>([])
  const [filingFrom, setFilingFrom] = useState('')
  const [filingTo, setFilingTo] = useState('')
  const [topK, setTopK] = useState(8)
  const [includeTrace, setIncludeTrace] = useState(true)

  const [response, setResponse] = useState<QueryResponse | null>(null)
  const [elapsed, setElapsed] = useState<number | null>(null)
  const [highlighted, setHighlighted] = useState<number | null>(null)
  const historyRef = useRef<Array<HistoryEntry>>(readHistory())

  const askMutation = useMutation({
    mutationFn: async (q: string) => {
      const start = performance.now()
      const r = await api.query(token, {
        dataset_id: datasetId,
        question: q,
        retrieval_mode: mode,
        include_trace: includeTrace,
        top_k: topK,
        filters: {
          ticker: tickers.length > 0 ? tickers : undefined,
          form_type: forms.length > 0 ? forms : undefined,
          filing_date_start: filingFrom || undefined,
          filing_date_end: filingTo || undefined,
        },
      })
      const end = performance.now()
      return { response: r, elapsed: end - start }
    },
    onSuccess: ({ response: r, elapsed: e }) => {
      setResponse(r)
      setElapsed(e)
      writeHistory({ question: question.trim(), ts: Date.now() })
      historyRef.current = readHistory()
      void queryClient.invalidateQueries({ queryKey: qk.traces.all() })
      if (r.insufficiency_reason) {
        toast.warn('Evidence may be insufficient', r.insufficiency_reason)
      }
    },
    onError: (err) => toastApiError(err, 'Query failed'),
  })

  function ask() {
    const q = question.trim()
    if (!q) return
    setResponse(null)
    setElapsed(null)
    setHighlighted(null)
    askMutation.mutate(q)
  }

  function reset() {
    setQuestion('')
    setTickers([])
    setForms([])
    setFilingFrom('')
    setFilingTo('')
    setResponse(null)
    setElapsed(null)
    setHighlighted(null)
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

  function toggleChip(
    list: Array<string>,
    value: string,
    setter: (next: Array<string>) => void,
  ) {
    if (list.includes(value)) setter(list.filter((v) => v !== value))
    else setter([...list, value])
  }

  function applyExample(q: string) {
    setQuestion(q)
  }

  const filterCount =
    tickers.length + forms.length + (filingFrom ? 1 : 0) + (filingTo ? 1 : 0)

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6 grid gap-5">
      {/* Composer */}
      <Card>
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <Search className="h-3.5 w-3.5" />
              QUERY WORKSPACE
            </span>
          }
          subtitle="Ask a question grounded in the ingested filings."
          actions={
            <div className="flex items-center gap-2">
              <RetrievalModeSelect value={mode} onChange={setMode} />
            </div>
          }
        />
        <CardBody className="grid gap-3">
          {/* History strip */}
          {historyRef.current.length > 0 && (
            <div className="flex items-center gap-2 overflow-x-auto pb-1">
              <span className="mono-label shrink-0">RECENT</span>
              {historyRef.current.slice(0, 5).map((h) => (
                <button
                  key={h.ts}
                  type="button"
                  onClick={() => applyExample(h.question)}
                  className="shrink-0 truncate max-w-[260px] rounded-[2px] border border-[var(--rule)] bg-[var(--surface-2)] px-2 py-1 font-mono text-[11px] text-[var(--ink-dim)] hover:bg-[var(--surface-3)] hover:text-[var(--ink)]"
                  title={h.question}
                >
                  {h.question}
                </button>
              ))}
            </div>
          )}

          {/* Question */}
          <Textarea
            placeholder={placeholder}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') ask()
            }}
            className="min-h-[88px] text-[14px] font-sans"
          />

          {/* Filter chips */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="mono-label inline-flex items-center gap-1">
              <Filter className="h-3 w-3" /> FILTERS
              {filterCount > 0 && (
                <Badge tone="accent" size="sm">
                  {filterCount}
                </Badge>
              )}
            </span>
            {tickers.map((t) => (
              <Chip
                key={`tk-${t}`}
                tone="accent"
                size="sm"
                onRemove={() => toggleChip(tickers, t, setTickers)}
              >
                ticker:{t}
              </Chip>
            ))}
            {forms.map((f) => (
              <Chip
                key={`fm-${f}`}
                tone="accent"
                size="sm"
                onRemove={() => toggleChip(forms, f, setForms)}
              >
                form:{f}
              </Chip>
            ))}
            {filingFrom && (
              <Chip tone="accent" size="sm" onRemove={() => setFilingFrom('')}>
                filed≥{filingFrom}
              </Chip>
            )}
            {filingTo && (
              <Chip tone="accent" size="sm" onRemove={() => setFilingTo('')}>
                filed≤{filingTo}
              </Chip>
            )}

            <Collapsible className="flex items-center">
              <CollapsibleTrigger className="ml-auto h-7 px-2 mono-label">
                <Cog className="h-3 w-3" />
                advanced
              </CollapsibleTrigger>
            </Collapsible>
          </div>

          <Collapsible defaultOpen>
            <CollapsibleContent>
              <div className="grid gap-3 rounded-[3px] border border-[var(--rule)] bg-[var(--surface-2)] p-3 md:grid-cols-[1fr_1fr_220px]">
                <Field label="TICKER" hint="pick from your dataset">
                  <div className="flex flex-wrap gap-1.5">
                    {allTickers.slice(0, 30).map((t) => {
                      const active = tickers.includes(t)
                      return (
                        <button
                          key={t}
                          type="button"
                          onClick={() => toggleChip(tickers, t, setTickers)}
                          className={`h-6 rounded-[2px] border px-2 font-mono text-[11px] transition-colors ${
                            active
                              ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]'
                              : 'border-[var(--rule-strong)] bg-[var(--surface)] text-[var(--ink-dim)] hover:bg-[var(--surface-3)]'
                          }`}
                        >
                          {t}
                        </button>
                      )
                    })}
                    {allTickers.length === 0 && (
                      <span className="font-mono text-[11px] text-[var(--ink-muted)]">
                        ingest documents first
                      </span>
                    )}
                  </div>
                </Field>

                <Field label="FORM TYPE">
                  <div className="flex flex-wrap gap-1.5">
                    {allForms.map((f) => {
                      const active = forms.includes(f)
                      return (
                        <button
                          key={f}
                          type="button"
                          onClick={() => toggleChip(forms, f, setForms)}
                          className={`h-6 rounded-[2px] border px-2 font-mono text-[11px] uppercase transition-colors ${
                            active
                              ? 'border-[var(--cite)] bg-[var(--cite-soft)] text-[var(--cite)]'
                              : 'border-[var(--rule-strong)] bg-[var(--surface)] text-[var(--ink-dim)] hover:bg-[var(--surface-3)]'
                          }`}
                        >
                          {f}
                        </button>
                      )
                    })}
                  </div>
                </Field>

                <div className="grid gap-2.5">
                  <Field label="FILED FROM">
                    <Input
                      type="date"
                      value={filingFrom}
                      onChange={(e) => setFilingFrom(e.target.value)}
                    />
                  </Field>
                  <Field label="FILED TO">
                    <Input
                      type="date"
                      value={filingTo}
                      onChange={(e) => setFilingTo(e.target.value)}
                    />
                  </Field>
                </div>

                <div className="md:col-span-3 grid gap-3 md:grid-cols-[1fr_auto] border-t border-[var(--rule)] pt-3">
                  <Field
                    label={
                      <span className="inline-flex items-center justify-between w-full">
                        <span>TOP-K</span>
                        <span className="font-mono numeric text-[11px] text-[var(--ink-dim)]">
                          {topK}
                        </span>
                      </span>
                    }
                  >
                    <Slider
                      value={[topK]}
                      min={1}
                      max={20}
                      step={1}
                      onValueChange={([v]) => setTopK(v)}
                    />
                  </Field>
                  <label className="inline-flex items-center gap-2 text-[12px] text-[var(--ink-dim)]">
                    <Switch
                      checked={includeTrace}
                      onCheckedChange={(v) => setIncludeTrace(Boolean(v))}
                    />
                    persist trace
                  </label>
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>

          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={reset}
              leading={<RotateCcw className="h-3.5 w-3.5" />}
            >
              Reset
            </Button>
            <div className="ml-auto flex items-center gap-2">
              <span className="font-mono text-[10.5px] text-[var(--ink-muted)]">
                <Kbd>⌘</Kbd>
                <span className="mx-0.5">+</span>
                <Kbd>↵</Kbd>
              </span>
              <Button
                onClick={ask}
                disabled={!question.trim() || askMutation.isPending}
                leading={
                  askMutation.isPending ? null : (
                    <CornerDownLeft className="h-3.5 w-3.5" />
                  )
                }
              >
                {askMutation.isPending ? 'Asking…' : 'Ask'}
              </Button>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* Response */}
      {askMutation.isPending && (
        <Card>
          <CardBody className="grid gap-3">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-[88%]" />
            <Skeleton className="h-5 w-[70%]" />
          </CardBody>
        </Card>
      )}

      {response && !askMutation.isPending && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_440px]">
          <Card>
            <CardHeader
              title={
                <span className="inline-flex items-center gap-2">
                  <Sparkles className="h-3.5 w-3.5 text-[var(--accent)]" />
                  ANSWER
                </span>
              }
              actions={
                <div className="flex items-center gap-3 text-[11.5px]">
                  <ConfidenceMeter value={response.confidence} />
                  {elapsed !== null && (
                    <span className="font-mono text-[11px] text-[var(--ink-muted)]">
                      {formatDuration(elapsed)}
                    </span>
                  )}
                </div>
              }
            />
            <CardBody className="grid gap-3">
              <AnswerArticle
                answer={response.answer}
                highlightCitation={highlighted}
                onCitationClick={jumpToCitation}
              />
              {response.insufficiency_reason && (
                <div className="flex items-start gap-2 rounded-[3px] border border-[var(--warn)]/30 bg-[var(--warn-soft)] px-3 py-2">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-[var(--warn)] mt-0.5" />
                  <div className="text-[12px] text-[var(--ink)]">
                    <div className="font-medium text-[var(--warn)]">
                      Evidence insufficient
                    </div>
                    <p className="mt-0.5 text-[var(--ink-dim)]">
                      {response.insufficiency_reason}
                    </p>
                  </div>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-3 border-t border-[var(--rule)] pt-3">
                <Badge tone="cite" size="sm">
                  {mode.replace('_', ' ')}
                </Badge>
                <span className="font-mono text-[11px] text-[var(--ink-muted)]">
                  {response.citations.length} citation
                  {response.citations.length === 1 ? '' : 's'} ·{' '}
                  {response.evidence.length} chunks
                </span>
                <Button
                  variant="ghost"
                  size="xs"
                  asChild
                  className="ml-auto"
                  trailing={<ArrowRight className="h-3 w-3" />}
                >
                  <Link {...paths.trace(response.trace_id)}>open trace</Link>
                </Button>
              </div>
            </CardBody>
          </Card>

          <div className="grid gap-3">
            <Card>
              <CardHeader
                title="CITATIONS"
                subtitle={`${response.citations.length}`}
              />
              <CardBody className="grid gap-2">
                {response.citations.length === 0 ? (
                  <p className="text-[12px] text-[var(--ink-muted)]">
                    No citations.
                  </p>
                ) : (
                  response.citations.map((c, i) => (
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

            <Card>
              <CardHeader
                title="EVIDENCE"
                subtitle={`${response.evidence.length} chunks ranked`}
              />
              <CardBody>
                <EvidenceList items={response.evidence} />
              </CardBody>
            </Card>
          </div>
        </div>
      )}

      {!response && !askMutation.isPending && (
        <Card>
          <CardBody>
            <EmptyState
              icon={Search}
              title="Ask something"
              description="Try one of the example questions below, or filter by ticker and form type to narrow the search."
              action={
                <div className="flex flex-wrap items-center justify-center gap-1.5 max-w-2xl">
                  {EXAMPLE_QUESTIONS.map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => applyExample(q)}
                      className="text-[11.5px] text-[var(--ink-dim)] border border-[var(--rule)] rounded-[2px] px-2 py-1 hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              }
            />
          </CardBody>
        </Card>
      )}
    </div>
  )
}
