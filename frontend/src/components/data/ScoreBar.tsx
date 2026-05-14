import { cn } from '#/lib/cn'

export function ScoreBar({
  value,
  max = 1,
  segments = 10,
  className,
  showValue = true,
  tone = 'accent',
}: {
  value: number
  max?: number
  segments?: number
  className?: string
  showValue?: boolean
  tone?: 'accent' | 'ok' | 'warn' | 'bad'
}) {
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0
  const filled = Math.round(ratio * segments)
  const colorMap = {
    accent: 'text-[var(--accent)]',
    ok: 'text-[var(--ok)]',
    warn: 'text-[var(--warn)]',
    bad: 'text-[var(--bad)]',
  }
  const dim = 'text-[var(--rule-strong)]'
  const bars = Array.from({ length: segments }, (_, i) =>
    i < filled ? '▮' : '▯',
  ).join('')
  return (
    <span className={cn('inline-flex items-center gap-2 font-mono text-[11px]', className)}>
      <span className={cn(colorMap[tone], dim, 'tracking-tight')} aria-hidden>
        <span className={colorMap[tone]}>{bars.slice(0, filled)}</span>
        <span className={dim}>{bars.slice(filled)}</span>
      </span>
      {showValue && (
        <span className="numeric text-[var(--ink-dim)] min-w-[36px] text-right">
          {value.toFixed(value >= 1 ? 2 : 3)}
        </span>
      )}
    </span>
  )
}
