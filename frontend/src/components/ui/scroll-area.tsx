import * as RxScrollArea from '@radix-ui/react-scroll-area'
import type { ComponentPropsWithoutRef } from 'react'
import { forwardRef } from 'react'

import { cn } from '#/lib/cn'

export const ScrollArea = forwardRef<
  React.ElementRef<typeof RxScrollArea.Root>,
  ComponentPropsWithoutRef<typeof RxScrollArea.Root> & { viewportClassName?: string }
>(function ScrollArea({ className, viewportClassName, children, ...props }, ref) {
  return (
    <RxScrollArea.Root
      ref={ref}
      className={cn('relative overflow-hidden', className)}
      {...props}
    >
      <RxScrollArea.Viewport className={cn('h-full w-full rounded-[inherit]', viewportClassName)}>
        {children}
      </RxScrollArea.Viewport>
      <ScrollBar />
      <RxScrollArea.Corner />
    </RxScrollArea.Root>
  )
})

function ScrollBar() {
  return (
    <RxScrollArea.Scrollbar
      orientation="vertical"
      className="flex w-2 touch-none select-none p-0.5 transition-colors"
    >
      <RxScrollArea.Thumb className="relative flex-1 rounded-full bg-[var(--rule-strong)] hover:bg-[var(--ink-muted)]" />
    </RxScrollArea.Scrollbar>
  )
}
