import type { ReactNode } from 'react'

import { cn } from '#/lib/cn'

export type KVRow = {
  key: ReactNode
  value: ReactNode
  mono?: boolean
  copyable?: boolean
  rowKey?: string
}

export function KeyValueGrid({
  rows,
  className,
  dense,
}: {
  rows: ReadonlyArray<KVRow>
  className?: string
  dense?: boolean
}) {
  return (
    <dl
      className={cn(
        'grid grid-cols-[max-content_minmax(0,1fr)] gap-x-6',
        dense ? 'gap-y-1' : 'gap-y-2',
        className,
      )}
    >
      {rows.map((row, i) => (
        <Row key={row.rowKey ?? i} row={row} />
      ))}
    </dl>
  )
}

function Row({ row }: { row: KVRow }) {
  return (
    <>
      <dt className="mono-label self-start pt-0.5 whitespace-nowrap">{row.key}</dt>
      <dd
        className={cn(
          'text-[12.5px] text-[var(--ink)] break-words',
          row.mono && 'font-mono text-[12px]',
        )}
      >
        {row.copyable && typeof row.value === 'string' ? (
          <CopyValue value={row.value} mono={row.mono} />
        ) : (
          row.value
        )}
      </dd>
    </>
  )
}

function CopyValue({ value, mono }: { value: string; mono?: boolean }) {
  return (
    <button
      type="button"
      onClick={() => {
        try {
          void navigator.clipboard.writeText(value)
        } catch {
          /* ignore */
        }
      }}
      title="Copy"
      className={cn(
        'group inline-flex max-w-full items-center gap-1.5 rounded-[2px] px-1 -mx-1 py-0.5 text-left',
        'hover:bg-[var(--surface-2)] transition-colors',
        mono && 'font-mono text-[12px]',
      )}
    >
      <span className="truncate">{value}</span>
      <svg
        className="h-3 w-3 shrink-0 text-[var(--ink-muted)] opacity-0 transition-opacity group-hover:opacity-100"
        viewBox="0 0 12 12"
        fill="none"
      >
        <rect x="3" y="3" width="6.5" height="6.5" rx="1" stroke="currentColor" strokeWidth="1" />
        <rect x="1.5" y="1.5" width="6.5" height="6.5" rx="1" stroke="currentColor" strokeWidth="1" />
      </svg>
    </button>
  )
}
