import { ExternalLink, TableIcon } from 'lucide-react'

import { Badge } from '#/components/ui/badge'
import { ScoreBar } from '#/components/data/ScoreBar'
import type { Evidence } from '#/lib/api'
import { cn } from '#/lib/cn'
import { openSourcePdf } from '#/lib/pdfViewer'
import { useToken } from '#/providers/TokenProvider'

export function EvidenceList({ items }: { items: ReadonlyArray<Evidence> }) {
  const { token } = useToken()

  if (items.length === 0) {
    return (
      <p className="text-[12px] text-[var(--ink-muted)]">
        No evidence chunks returned.
      </p>
    )
  }
  const max = Math.max(...items.map((i) => i.score), 1e-9)
  return (
    <ol className="grid gap-2">
      {items.map((e, idx) => {
        const pageLabel =
          e.page_end !== e.page_start
            ? `${e.page_start}–${e.page_end}`
            : `${e.page_start}`
        return (
          <li key={e.chunk_id}>
            <button
              type="button"
              onClick={() =>
                void openSourcePdf({
                  token,
                  documentId: e.document_id,
                  page: e.page_start,
                })
              }
              title={`Open PDF at page ${e.page_start}`}
              aria-label={`Open source PDF for ${e.ticker} ${e.form_type} at page ${e.page_start}`}
              className={cn(
                'group block w-full text-left rounded-[3px] border border-[var(--rule)] bg-[var(--surface)] p-2.5 transition-all cursor-pointer',
                'hover:border-[var(--accent)]/40 hover:bg-[var(--surface-2)]',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40',
              )}
            >
              <div className="flex flex-wrap items-center gap-2 text-[11.5px]">
                <span className="font-mono font-semibold text-[var(--ink-dim)] w-5">
                  #{idx + 1}
                </span>
                <span className="font-mono font-medium text-[var(--ink)]">
                  {e.ticker}
                </span>
                <Badge tone="neutral" size="sm">
                  {e.form_type}
                </Badge>
                {e.contains_table && (
                  <Badge tone="warn" size="sm">
                    <TableIcon className="h-2.5 w-2.5" /> table
                  </Badge>
                )}
                <span className="inline-flex items-center gap-1 font-mono text-[10.5px] text-[var(--ink-muted)] group-hover:text-[var(--accent)]">
                  p. {pageLabel}
                  <ExternalLink className="h-2.5 w-2.5" />
                </span>
                <span className="ml-auto">
                  <ScoreBar value={e.score} max={max} segments={8} />
                </span>
              </div>
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-[var(--ink-dim)] line-clamp-3">
                {e.snippet}
              </p>
            </button>
          </li>
        )
      })}
    </ol>
  )
}
