import { cn } from '#/lib/cn'

export function ConfidenceMeter({
  value,
  className,
}: {
  value: number
  className?: string
}) {
  const pct = Math.round(value * 100)
  const tone = value >= 0.8 ? 'ok' : value >= 0.5 ? 'warn' : 'bad'
  const colorClass =
    tone === 'ok' ? 'text-[var(--ok)] bg-[var(--ok)]' : tone === 'warn' ? 'text-[var(--warn)] bg-[var(--warn)]' : 'text-[var(--bad)] bg-[var(--bad)]'
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <span className="mono-label">CONF</span>
      <span className="relative inline-block h-1.5 w-20 rounded-full bg-[var(--surface-2)] overflow-hidden">
        <span
          className={cn('absolute inset-y-0 left-0', colorClass.split(' ')[1])}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className={cn('font-mono numeric text-[12px]', colorClass.split(' ')[0])}>
        {pct}%
      </span>
    </span>
  )
}
