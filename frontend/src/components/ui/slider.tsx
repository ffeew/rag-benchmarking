import * as RxSlider from '@radix-ui/react-slider'
import type { ComponentPropsWithoutRef } from 'react'
import { forwardRef } from 'react'

import { cn } from '#/lib/cn'

export const Slider = forwardRef<
  React.ElementRef<typeof RxSlider.Root>,
  ComponentPropsWithoutRef<typeof RxSlider.Root>
>(function Slider({ className, ...props }, ref) {
  return (
    <RxSlider.Root
      ref={ref}
      className={cn('relative flex w-full touch-none select-none items-center', className)}
      {...props}
    >
      <RxSlider.Track className="relative h-1 w-full grow overflow-hidden rounded-full bg-[var(--surface-2)]">
        <RxSlider.Range className="absolute h-full bg-[var(--accent)]" />
      </RxSlider.Track>
      <RxSlider.Thumb className="block h-3.5 w-3.5 rounded-full border border-[var(--accent)] bg-[var(--bg)] shadow-sm transition-colors hover:bg-[var(--accent-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-ring)]" />
    </RxSlider.Root>
  )
})
