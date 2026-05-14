import { cn } from '#/lib/cn'

import type { BadgeTone } from './badge'
import { toneForStatus } from './badge'

const toneVar: Record<BadgeTone, string> = {
  ok: 'bg-[var(--ok)]',
  warn: 'bg-[var(--warn)]',
  bad: 'bg-[var(--bad)]',
  accent: 'bg-[var(--accent)]',
  cite: 'bg-[var(--cite)]',
  neutral: 'bg-[var(--ink-muted)]',
  outline: 'bg-[var(--ink-muted)]',
}

const pulseable = new Set<BadgeTone>(['warn', 'accent'])

export function StatusDot({
  status,
  tone,
  size = 8,
  pulse,
  className,
}: {
  status?: string | null
  tone?: BadgeTone
  size?: number
  pulse?: boolean
  className?: string
}) {
  const resolved = tone ?? toneForStatus(status)
  const shouldPulse = pulse ?? (resolved === 'warn' || pulseable.has(resolved))
  return (
    <span
      className={cn('relative inline-flex shrink-0 rounded-full', toneVar[resolved], className)}
      style={{ width: size, height: size }}
    >
      {shouldPulse && (
        <span
          className={cn('absolute inset-0 rounded-full opacity-60 animate-ping', toneVar[resolved])}
        />
      )}
    </span>
  )
}
