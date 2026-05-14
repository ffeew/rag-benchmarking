import { TableIcon } from 'lucide-react'

import { Badge } from '#/components/ui/badge'
import { ScoreBar } from '#/components/data/ScoreBar'
import type { Evidence } from '#/lib/api'

export function EvidenceList({ items }: { items: ReadonlyArray<Evidence> }) {
  if (items.length === 0) {
    return <p className="text-[12px] text-[var(--ink-muted)]">No evidence chunks returned.</p>
  }
  const max = Math.max(...items.map((i) => i.score), 1e-9)
  return (
    <ol className="grid gap-2">
      {items.map((e, idx) => (
        <li
          key={e.chunk_id}
          className="rounded-[3px] border border-[var(--rule)] bg-[var(--surface)] p-2.5"
        >
          <div className="flex flex-wrap items-center gap-2 text-[11.5px]">
            <span className="font-mono font-semibold text-[var(--ink-dim)] w-5">
              #{idx + 1}
            </span>
            <span className="font-mono font-medium text-[var(--ink)]">{e.ticker}</span>
            <Badge tone="neutral" size="sm">
              {e.form_type}
            </Badge>
            {e.contains_table && (
              <Badge tone="warn" size="sm">
                <TableIcon className="h-2.5 w-2.5" /> table
              </Badge>
            )}
            <span className="font-mono text-[10.5px] text-[var(--ink-muted)]">
              p. {e.page_start}
              {e.page_end !== e.page_start ? `–${e.page_end}` : ''}
            </span>
            <span className="ml-auto">
              <ScoreBar value={e.score} max={max} segments={8} />
            </span>
          </div>
          <p className="mt-1.5 text-[11.5px] leading-relaxed text-[var(--ink-dim)] line-clamp-3">
            {e.snippet}
          </p>
        </li>
      ))}
    </ol>
  )
}
