import { cva } from 'class-variance-authority'
import type { VariantProps } from 'class-variance-authority'
import type { HTMLAttributes } from 'react'

import { cn } from '#/lib/cn'

const badgeStyles = cva(
  'inline-flex items-center gap-1 font-mono uppercase tracking-[0.08em] whitespace-nowrap',
  {
    variants: {
      tone: {
        neutral: 'text-[var(--ink-dim)] bg-[var(--surface-2)] border-[var(--rule)]',
        ok: 'text-[var(--ok)] bg-[var(--ok-soft)] border-transparent',
        warn: 'text-[var(--warn)] bg-[var(--warn-soft)] border-transparent',
        bad: 'text-[var(--bad)] bg-[var(--bad-soft)] border-transparent',
        accent: 'text-[var(--accent)] bg-[var(--accent-soft)] border-transparent',
        cite: 'text-[var(--cite)] bg-[var(--cite-soft)] border-transparent',
        outline: 'text-[var(--ink-dim)] bg-transparent border-[var(--rule-strong)]',
      },
      size: {
        sm: 'h-[18px] px-1.5 text-[10px] rounded-[2px] border',
        md: 'h-5 px-2 text-[10.5px] rounded-[3px] border',
        lg: 'h-6 px-2 text-[11px] rounded-[3px] border',
      },
    },
    defaultVariants: { tone: 'neutral', size: 'md' },
  },
)

export type BadgeTone = NonNullable<VariantProps<typeof badgeStyles>['tone']>

export function Badge({
  className,
  tone,
  size,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeStyles>) {
  return <span className={cn(badgeStyles({ tone, size }), className)} {...props} />
}

export function toneForStatus(status?: string | null): BadgeTone {
  if (!status) return 'neutral'
  const normalized = status.toLowerCase()
  if (['completed', 'ready', 'ok', 'success', 'verified'].includes(normalized)) return 'ok'
  if (['failed', 'degraded', 'error', 'cancelled', 'insufficient'].includes(normalized)) return 'bad'
  if (['running', 'queued', 'pending', 'in_progress', 'completed_with_errors', 'partial'].includes(normalized))
    return 'warn'
  return 'neutral'
}
