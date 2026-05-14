import * as RxSwitch from '@radix-ui/react-switch'
import type { ComponentPropsWithoutRef } from 'react'
import { forwardRef } from 'react'

import { cn } from '#/lib/cn'

export const Switch = forwardRef<
  React.ElementRef<typeof RxSwitch.Root>,
  ComponentPropsWithoutRef<typeof RxSwitch.Root>
>(function Switch({ className, ...props }, ref) {
  return (
    <RxSwitch.Root
      ref={ref}
      className={cn(
        'inline-flex h-4 w-7 shrink-0 items-center rounded-full border border-[var(--rule-strong)]',
        'bg-[var(--surface-2)] transition-colors',
        'data-[state=checked]:bg-[var(--accent)] data-[state=checked]:border-[var(--accent)]',
        'focus-visible:ring-2 focus-visible:ring-[var(--accent-ring)]',
        className,
      )}
      {...props}
    >
      <RxSwitch.Thumb className="block h-3 w-3 translate-x-0.5 rounded-full bg-[var(--ink)] transition-transform data-[state=checked]:translate-x-3.5 data-[state=checked]:bg-[var(--bg)]" />
    </RxSwitch.Root>
  )
})
