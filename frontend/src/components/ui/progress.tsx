import * as RxProgress from '@radix-ui/react-progress'

import { cn } from '#/lib/cn'

export function Progress({
  value,
  className,
  height = 4,
  showLabel,
}: {
  value: number
  className?: string
  height?: number
  showLabel?: boolean
}) {
  const clamped = Math.min(100, Math.max(0, value))
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <RxProgress.Root
        value={clamped}
        className="relative w-full overflow-hidden rounded-[2px] bg-[var(--surface-2)]"
        style={{ height }}
      >
        <RxProgress.Indicator
          className="h-full transition-transform duration-500 ease-out"
          style={{
            transform: `translateX(-${100 - clamped}%)`,
            background: 'var(--accent)',
          }}
        />
      </RxProgress.Root>
      {showLabel && (
        <span
          className="font-mono numeric text-[11px] text-[var(--ink-dim)] shrink-0"
          style={{ width: 38, textAlign: 'right' }}
        >
          {clamped.toFixed(0)}%
        </span>
      )}
    </div>
  )
}
