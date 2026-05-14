import type { ElementType, ReactNode } from 'react'

import { cn } from '#/lib/cn'

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ElementType
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 px-6 py-12 text-center',
        className,
      )}
    >
      {Icon && (
        <div className="flex h-9 w-9 items-center justify-center rounded-[4px] bg-[var(--surface-2)] border border-[var(--rule)]">
          <Icon className="h-4 w-4 text-[var(--ink-muted)]" />
        </div>
      )}
      <div>
        <p className="text-[13px] font-medium text-[var(--ink)]">{title}</p>
        {description && (
          <p className="mt-1 text-[12px] text-[var(--ink-muted)] max-w-sm">{description}</p>
        )}
      </div>
      {action}
    </div>
  )
}
