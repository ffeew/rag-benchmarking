import * as RxCheckbox from '@radix-ui/react-checkbox'
import { Check } from 'lucide-react'
import type { ComponentPropsWithoutRef } from 'react'
import { forwardRef } from 'react'

import { cn } from '#/lib/cn'

export const Checkbox = forwardRef<
  React.ElementRef<typeof RxCheckbox.Root>,
  ComponentPropsWithoutRef<typeof RxCheckbox.Root>
>(function Checkbox({ className, ...props }, ref) {
  return (
    <RxCheckbox.Root
      ref={ref}
      className={cn(
        'h-4 w-4 shrink-0 rounded-[2px] border border-[var(--rule-strong)] bg-[var(--surface)]',
        'transition-colors data-[state=checked]:bg-[var(--accent)] data-[state=checked]:border-[var(--accent)]',
        'focus-visible:ring-2 focus-visible:ring-[var(--accent-ring)]',
        'disabled:opacity-50',
        className,
      )}
      {...props}
    >
      <RxCheckbox.Indicator className="flex items-center justify-center text-[var(--bg)]">
        <Check className="h-3 w-3" strokeWidth={3} />
      </RxCheckbox.Indicator>
    </RxCheckbox.Root>
  )
})
