import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from '#/components/ui/button'
import { Select } from '#/components/ui/input'

export const DEFAULT_PAGE_SIZES = [25, 50, 100] as const

type Props = {
  total: number
  limit: number
  offset: number
  onChange: (next: { limit: number; offset: number }) => void
  pageSizes?: readonly number[]
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
  pageSizes = DEFAULT_PAGE_SIZES,
}: Props) {
  const page = Math.floor(offset / limit) + 1
  const totalPages = Math.max(1, Math.ceil(total / limit))
  const start = total === 0 ? 0 : offset + 1
  const end = Math.min(total, offset + limit)
  const prevDisabled = offset <= 0
  const nextDisabled = offset + limit >= total

  return (
    <div className="flex items-center justify-between border-t border-[var(--rule)] px-4 py-2 font-mono text-[11px] text-[var(--ink-muted)]">
      <div className="numeric">
        {total === 0 ? '0 results' : `${start}–${end} of ${total}`}
      </div>
      <div className="flex items-center gap-2">
        <Select
          value={String(limit)}
          onChange={(e) => onChange({ limit: Number(e.target.value), offset: 0 })}
          className="h-7 w-[88px] text-[12px]"
          aria-label="Rows per page"
        >
          {pageSizes.map((n) => (
            <option key={n} value={n}>
              {n}/page
            </option>
          ))}
        </Select>
        <span className="numeric">
          Page {page} of {totalPages}
        </span>
        <Button
          size="xs"
          variant="ghost"
          disabled={prevDisabled}
          onClick={() => onChange({ limit, offset: Math.max(0, offset - limit) })}
          leading={<ChevronLeft className="h-3 w-3" />}
          aria-label="Previous page"
        >
          Prev
        </Button>
        <Button
          size="xs"
          variant="ghost"
          disabled={nextDisabled}
          onClick={() => onChange({ limit, offset: offset + limit })}
          trailing={<ChevronRight className="h-3 w-3" />}
          aria-label="Next page"
        >
          Next
        </Button>
      </div>
    </div>
  )
}
