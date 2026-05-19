import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '#/lib/cn'

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'bg-[var(--surface)] border border-[var(--rule)] rounded-[4px] min-w-0',
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({
  title,
  subtitle,
  actions,
  className,
  children,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  className?: string
  children?: ReactNode
}) {
  return (
    <div
      className={cn(
        'flex items-start justify-between gap-3 px-4 py-3 border-b border-[var(--rule)]',
        className,
      )}
    >
      <div className="min-w-0 flex-1">
        {title && (
          <div className="mono-label text-[var(--ink-muted)]">
            {title}
          </div>
        )}
        {subtitle && (
          <div className="mt-0.5 text-[13px] text-[var(--ink-dim)] truncate">{subtitle}</div>
        )}
        {children}
      </div>
      {actions && <div className="flex items-center gap-1.5 shrink-0">{actions}</div>}
    </div>
  )
}

export function CardBody({
  className,
  children,
  padded = true,
}: {
  className?: string
  children: ReactNode
  padded?: boolean
}) {
  return <div className={cn(padded && 'p-4', className)}>{children}</div>
}
