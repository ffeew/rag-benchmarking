import { ChevronRight, Layers } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '#/components/ui/badge'
import { Card, CardHeader } from '#/components/ui/card'
import { ScoreBar } from '#/components/data/ScoreBar'
import { Sparkline } from '#/components/data/Sparkline'
import { cn } from '#/lib/cn'
import { formatScore, truncate } from '#/lib/format'

type Candidate = {
  rank?: number
  score?: number
  rerank_score?: number
  rrf_score?: number
  ticker?: string
  form_type?: string
  page_start?: number
  page_end?: number
  page_number?: number
  chunk_id?: string
  snippet?: string
  text?: string
}

export function RetrievalCallCard({
  call,
  index,
}: {
  call: Record<string, unknown>
  index: number
}) {
  const [open, setOpen] = useState(index === 0)

  const queryText = String(
    call['query'] ?? call['query_text'] ?? call['rewritten'] ?? '',
  )
  const candidatesRaw = (call['candidates'] ??
    call['results'] ??
    call['top'] ??
    []) as Array<Candidate>
  const candidates = Array.isArray(candidatesRaw) ? candidatesRaw : []
  const scoresRaw = candidates
    .map((c) => Number(c.rerank_score ?? c.score ?? c.rrf_score ?? 0))
    .filter((n) => Number.isFinite(n))
  const maxScore = scoresRaw.length > 0 ? Math.max(...scoresRaw, 1e-9) : 1
  const rerankedRaw = call['reranked'] ?? call['rerank_used']
  const reranked = typeof rerankedRaw === 'boolean' ? rerankedRaw : null

  return (
    <Card>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="block w-full text-left"
      >
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <ChevronRight
                className={cn(
                  'h-3 w-3 transition-transform',
                  open && 'rotate-90',
                )}
              />
              <Layers className="h-3.5 w-3.5 text-[var(--cite)]" />
              CALL #{index + 1}
              {reranked != null && (
                <Badge tone={reranked ? 'ok' : 'neutral'} size="sm">
                  {reranked ? 'rerank' : 'rrf'}
                </Badge>
              )}
            </span>
          }
          actions={
            <div className="flex items-center gap-2">
              <Sparkline values={scoresRaw} width={80} height={20} />
              <span className="font-mono text-[11px] text-[var(--ink-dim)]">
                {candidates.length}
              </span>
            </div>
          }
        />
      </button>
      {open && (
        <div className="border-t border-[var(--rule)]">
          {queryText && (
            <div className="border-b border-[var(--rule)] bg-[var(--surface-2)] px-4 py-2">
              <div className="mono-label mb-0.5">QUERY</div>
              <code className="font-mono text-[11.5px] text-[var(--ink)] leading-relaxed">
                {queryText}
              </code>
            </div>
          )}
          {candidates.length === 0 ? (
            <p className="px-4 py-3 font-mono text-[11px] text-[var(--ink-muted)]">
              No candidates recorded.
            </p>
          ) : (
            <ul className="divide-y divide-[var(--rule)]">
              {candidates.slice(0, 20).map((c, i) => {
                const score = Number(
                  c.rerank_score ?? c.score ?? c.rrf_score ?? 0,
                )
                const page = c.page_start ?? c.page_number
                return (
                  <li
                    key={`${c.chunk_id ?? i}`}
                    className="grid grid-cols-[40px_1fr_120px] items-center gap-3 px-4 py-2"
                  >
                    <span className="font-mono numeric text-[11.5px] text-[var(--ink-dim)]">
                      #{c.rank ?? i + 1}
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5 text-[11.5px]">
                        {c.ticker && (
                          <span className="font-mono font-medium text-[var(--ink)]">
                            {c.ticker}
                          </span>
                        )}
                        {c.form_type && (
                          <Badge tone="neutral" size="sm">
                            {c.form_type}
                          </Badge>
                        )}
                        {page != null && (
                          <span className="font-mono text-[10.5px] text-[var(--ink-muted)]">
                            p. {page}
                          </span>
                        )}
                      </div>
                      {(c.snippet || c.text) && (
                        <p className="mt-0.5 font-mono text-[10.5px] text-[var(--ink-muted)] truncate">
                          {truncate(String(c.snippet ?? c.text ?? ''), 90)}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center justify-end gap-2 text-[11px]">
                      <ScoreBar
                        value={score}
                        max={maxScore}
                        segments={6}
                        showValue={false}
                      />
                      <span className="font-mono numeric text-[10.5px] text-[var(--ink-dim)] w-10 text-right">
                        {formatScore(score)}
                      </span>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </Card>
  )
}
