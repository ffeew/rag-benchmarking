import type { CSSProperties } from 'react'

import { cn } from '#/lib/cn'

export function Skeleton({
  className,
  style,
}: {
  className?: string
  style?: CSSProperties
}) {
  return <div className={cn('skeleton', className)} style={style} />
}

export function SkeletonRows({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-7" style={{ opacity: 1 - i * 0.08 }} />
      ))}
    </div>
  )
}
