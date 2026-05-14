import type { ReactNode } from 'react'

import { cn } from '#/lib/cn'

import { Label } from './label'

export function Field({
  label,
  hint,
  error,
  required,
  htmlFor,
  children,
  className,
  inline,
}: {
  label?: ReactNode
  hint?: ReactNode
  error?: string | null
  required?: boolean
  htmlFor?: string
  children: ReactNode
  className?: string
  inline?: boolean
}) {
  return (
    <div className={cn('flex', inline ? 'flex-row items-center gap-3' : 'flex-col gap-1.5', className)}>
      {label && (
        <Label htmlFor={htmlFor} className={cn(inline && 'min-w-[120px]')}>
          {label}
          {required && <span className="ml-0.5 text-[var(--bad)]">*</span>}
        </Label>
      )}
      <div className={cn('flex flex-col gap-1', inline && 'flex-1')}>
        {children}
        {error ? (
          <p className="font-mono text-[11px] text-[var(--bad)] leading-tight">{error}</p>
        ) : hint ? (
          <p className="text-[11.5px] text-[var(--ink-muted)] leading-tight">{hint}</p>
        ) : null}
      </div>
    </div>
  )
}
