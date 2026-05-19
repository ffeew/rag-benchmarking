import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react'

import { cn } from '#/lib/cn'

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className={cn('w-full', className)}>
      <table className="w-full border-collapse text-[13px]" {...props} />
    </div>
  )
}

export function THead({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn(
        'border-b border-[var(--rule)] bg-[var(--surface-2)]',
        className,
      )}
      {...props}
    />
  )
}

export function TBody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('', className)} {...props} />
}

export function TR({
  className,
  interactive,
  selected,
  ...props
}: HTMLAttributes<HTMLTableRowElement> & {
  interactive?: boolean
  selected?: boolean
}) {
  return (
    <tr
      className={cn(
        'border-b border-[var(--rule)]',
        interactive && 'cursor-pointer hover:bg-[var(--surface-2)] transition-colors',
        selected && 'bg-[var(--accent-soft)]',
        className,
      )}
      {...props}
    />
  )
}

export function TH({
  className,
  align = 'left',
  ...props
}: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      align={align}
      className={cn(
        'mono-label py-2 px-3 text-left font-medium text-[var(--ink-muted)]',
        className,
      )}
      {...props}
    />
  )
}

export function TD({
  className,
  align,
  numeric,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }) {
  return (
    <td
      align={align}
      className={cn(
        'py-2 px-3 text-[12.5px] text-[var(--ink)] align-top break-words',
        numeric && 'font-mono numeric text-right',
        className,
      )}
      {...props}
    />
  )
}
