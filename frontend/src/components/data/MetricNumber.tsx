import type { ReactNode } from 'react'

import { cn } from '#/lib/cn'

export function MetricNumber({
  label,
  value,
  unit,
  trailing,
  delta,
  className,
  size = 'md',
}: {
  label: ReactNode
  value: ReactNode
  unit?: ReactNode
  trailing?: ReactNode
  delta?: { value: ReactNode; tone?: 'ok' | 'bad' | 'neutral' }
  className?: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
}) {
  const sizes = {
    sm: 'text-[18px]',
    md: 'text-[24px]',
    lg: 'text-[30px]',
    xl: 'text-[38px]',
  }
  const deltaColor =
    delta?.tone === 'ok'
      ? 'text-[var(--ok)]'
      : delta?.tone === 'bad'
        ? 'text-[var(--bad)]'
        : 'text-[var(--ink-muted)]'

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div className="mono-label">{label}</div>
      <div className="flex items-baseline gap-1.5">
        <span className={cn('font-mono numeric font-medium leading-none text-[var(--ink)]', sizes[size])}>
          {value}
        </span>
        {unit && (
          <span className="font-mono text-[11px] uppercase tracking-wide text-[var(--ink-muted)]">
            {unit}
          </span>
        )}
        {trailing}
      </div>
      {delta && (
        <div className={cn('font-mono text-[11px] numeric', deltaColor)}>
          {delta.value}
        </div>
      )}
    </div>
  )
}
