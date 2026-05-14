import * as RxPopover from '@radix-ui/react-popover'
import type { ComponentPropsWithoutRef } from 'react'

import { cn } from '#/lib/cn'

export const Popover = RxPopover.Root
export const PopoverTrigger = RxPopover.Trigger

export function PopoverContent({
  className,
  align = 'start',
  sideOffset = 6,
  ...props
}: ComponentPropsWithoutRef<typeof RxPopover.Content>) {
  return (
    <RxPopover.Portal>
      <RxPopover.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          'z-50 rounded-[4px] p-3 animate-scale-in',
          'bg-[var(--surface)] border border-[var(--rule-strong)] shadow-[var(--shadow-pop)]',
          'text-[var(--ink)]',
          className,
        )}
        {...props}
      />
    </RxPopover.Portal>
  )
}
