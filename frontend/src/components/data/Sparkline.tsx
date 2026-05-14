import { cn } from '#/lib/cn'

export function Sparkline({
  values,
  height = 28,
  width = 120,
  className,
  highlightIndex,
  tone = 'accent',
}: {
  values: ReadonlyArray<number>
  height?: number
  width?: number
  className?: string
  highlightIndex?: number
  tone?: 'accent' | 'cite'
}) {
  if (values.length === 0) {
    return <span className={cn('inline-block text-[var(--ink-muted)] text-[11px]', className)}>—</span>
  }
  const max = Math.max(...values, 1e-9)
  const min = Math.min(...values, 0)
  const range = max - min || 1
  const padding = 1
  const barCount = values.length
  const gap = Math.max(0.5, Math.min(2, width / barCount / 4))
  const barWidth = Math.max(1, (width - gap * (barCount - 1) - padding * 2) / barCount)
  const stroke = tone === 'accent' ? 'var(--accent)' : 'var(--cite)'

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn('overflow-visible', className)}
      aria-hidden
    >
      {values.map((v, i) => {
        const h = Math.max(2, ((v - min) / range) * (height - padding * 2))
        const x = padding + i * (barWidth + gap)
        const y = height - padding - h
        const isHighlight = highlightIndex === i
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={barWidth}
            height={h}
            fill={isHighlight ? stroke : 'var(--ink-muted)'}
            opacity={isHighlight ? 1 : 0.55}
            rx={0.5}
          />
        )
      })}
    </svg>
  )
}
