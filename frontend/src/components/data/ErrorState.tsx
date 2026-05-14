import { AlertTriangle, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '#/lib/cn'

import { Button } from '../ui/button'

export function ErrorState({
  title = 'Something went wrong',
  description,
  error,
  onRetry,
  retryLabel = 'Try again',
  className,
  extra,
}: {
  title?: ReactNode
  description?: ReactNode
  error?: unknown
  onRetry?: () => void
  retryLabel?: string
  className?: string
  extra?: ReactNode
}) {
  const message = description ?? (error instanceof Error ? error.message : undefined)
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 px-6 py-12 text-center',
        className,
      )}
    >
      <div className="flex h-9 w-9 items-center justify-center rounded-[4px] bg-[var(--bad-soft)] border border-[var(--bad)]/30">
        <AlertTriangle className="h-4 w-4 text-[var(--bad)]" />
      </div>
      <div>
        <p className="text-[13px] font-medium text-[var(--ink)]">{title}</p>
        {message && (
          <p className="mt-1 max-w-md font-mono text-[11.5px] text-[var(--ink-muted)] break-all">
            {message}
          </p>
        )}
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry} leading={<RefreshCw className="h-3.5 w-3.5" />}>
          {retryLabel}
        </Button>
      )}
      {extra}
    </div>
  )
}
