import { ExternalLink } from 'lucide-react'
import type { KeyboardEvent, MouseEvent } from 'react'

import { Badge } from '#/components/ui/badge'
import type { Citation } from '#/lib/api'
import { cn } from '#/lib/cn'
import { formatDate } from '#/lib/format'
import { openSourcePdf } from '#/lib/pdfViewer'
import { useToken } from '#/providers/TokenProvider'

export function CitationCard({
  citation,
  index,
  highlighted,
  onSelect,
}: {
  citation: Citation
  index: number
  highlighted?: boolean
  onSelect?: (index: number) => void
}) {
  const { token } = useToken()

  function handleSelect() {
    onSelect?.(index)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      handleSelect()
    }
  }

  function handleOpenPdf(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    void openSourcePdf({
      token,
      documentId: citation.document_id,
      page: citation.page_number,
    })
  }

  return (
    <div
      role="button"
      tabIndex={0}
      id={`citation-${index}`}
      data-citation-card={index}
      aria-label={`Citation ${index} — ${citation.label}`}
      onClick={handleSelect}
      onKeyDown={handleKeyDown}
      className={cn(
        'group block w-full text-left border rounded-[4px] p-3 transition-all cursor-pointer overflow-hidden',
        'bg-[var(--surface)] border-[var(--rule)]',
        'hover:border-[var(--cite)]/40 hover:bg-[var(--surface-2)]',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--cite)]/40',
        highlighted &&
          'border-[var(--cite)] bg-[var(--cite-soft)] ring-1 ring-[var(--cite)]/40',
      )}
    >
      <div className="flex items-start gap-2.5">
        <span className="inline-flex h-5 min-w-[22px] items-center justify-center rounded-[2px] border border-[var(--cite)]/30 bg-[var(--cite-soft)] px-1 font-mono text-[10.5px] font-semibold text-[var(--cite)]">
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-[var(--ink)]">
            <span className="font-mono font-medium">{citation.ticker}</span>
            <span className="text-[var(--ink-muted)]">·</span>
            <Badge tone="neutral" size="sm">
              {citation.form_type}
            </Badge>
            <span className="text-[var(--ink-muted)]">·</span>
            <span className="font-mono text-[11px] text-[var(--ink-dim)]">
              p. {citation.page_number}
            </span>
            <span className="ml-auto font-mono text-[10.5px] text-[var(--ink-muted)]">
              {formatDate(citation.filing_date)}
            </span>
          </div>
          <p className="mt-1.5 text-[11.5px] leading-relaxed text-[var(--ink-dim)] line-clamp-4 break-words group-hover:text-[var(--ink)]">
            {citation.snippet}
          </p>
          <button
            type="button"
            onClick={handleOpenPdf}
            title={`Open PDF at page ${citation.page_number}`}
            aria-label={`Open source PDF at page ${citation.page_number}`}
            className={cn(
              'mt-2 flex w-full items-center gap-1 rounded-[2px]',
              'font-mono text-[10px] text-[var(--ink-muted)]',
              'hover:text-[var(--accent)] hover:underline underline-offset-2',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40',
            )}
          >
            <ExternalLink className="h-2.5 w-2.5 shrink-0" />
            <span className="min-w-0 flex-1 truncate text-left">{citation.minio_key}</span>
          </button>
        </div>
      </div>
    </div>
  )
}
