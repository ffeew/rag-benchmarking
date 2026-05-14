import type { HTMLAttributes } from 'react'

import { cn } from '#/lib/cn'

export function Kbd({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        'inline-flex h-5 min-w-[20px] items-center justify-center px-1',
        'rounded-[3px] border border-[var(--rule-strong)] bg-[var(--surface-2)]',
        'font-mono text-[10.5px] text-[var(--ink-dim)] tracking-tight',
        className,
      )}
      {...props}
    />
  )
}
