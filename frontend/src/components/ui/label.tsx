import type { LabelHTMLAttributes } from 'react'

import { cn } from '#/lib/cn'

export function Label({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        'mono-label inline-block',
        className,
      )}
      {...props}
    />
  )
}
