import { Fragment } from 'react'

import { parseAnswerCitations } from '#/lib/answer'
import { cn } from '#/lib/cn'

export function AnswerArticle({
  answer,
  onCitationClick,
  highlightCitation,
  className,
}: {
  answer: string
  onCitationClick?: (index: number) => void
  highlightCitation?: number | null
  className?: string
}) {
  const segments = parseAnswerCitations(answer)
  return (
    <article
      className={cn(
        'text-[15px] leading-[1.65] text-[var(--ink)] tracking-[-0.005em] whitespace-pre-wrap break-words',
        className,
      )}
    >
      {segments.map((seg, i) => {
        if (seg.kind === 'text') {
          return <Fragment key={i}>{seg.text}</Fragment>
        }
        const active = highlightCitation === seg.index
        return (
          <button
            key={i}
            type="button"
            onClick={() => onCitationClick?.(seg.index)}
            data-citation={seg.index}
            className={cn(
              'inline-flex items-center justify-center align-super mx-0.5 px-1 min-w-[18px] h-[17px]',
              'font-mono text-[10.5px] font-semibold rounded-[2px] transition-colors',
              'border border-[var(--cite)]/30 bg-[var(--cite-soft)] text-[var(--cite)]',
              'hover:bg-[var(--cite)] hover:text-white hover:border-[var(--cite)]',
              active && 'bg-[var(--cite)] text-white border-[var(--cite)] shadow-sm',
            )}
            aria-label={`Citation ${seg.label}`}
          >
            {seg.label}
          </button>
        )
      })}
    </article>
  )
}
