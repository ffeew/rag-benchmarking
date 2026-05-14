import * as RxTooltip from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'

import { cn } from '#/lib/cn'

export const TooltipProvider = RxTooltip.Provider

export function Tooltip({
  children,
  content,
  side = 'top',
  align = 'center',
  delay = 220,
  className,
  contentClassName,
  asChild = true,
}: {
  children: ReactNode
  content: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  delay?: number
  className?: string
  contentClassName?: string
  asChild?: boolean
}) {
  return (
    <RxTooltip.Root delayDuration={delay}>
      <RxTooltip.Trigger asChild={asChild} className={className}>
        {children}
      </RxTooltip.Trigger>
      <RxTooltip.Portal>
        <RxTooltip.Content
          side={side}
          align={align}
          sideOffset={6}
          className={cn(
            'z-50 max-w-xs px-2 py-1.5 rounded-[3px] animate-scale-in',
            'bg-[var(--surface)] border border-[var(--rule-strong)]',
            'text-[12px] text-[var(--ink)] shadow-[var(--shadow-pop)]',
            contentClassName,
          )}
        >
          {content}
          <RxTooltip.Arrow className="fill-[var(--surface)]" width={10} height={5} />
        </RxTooltip.Content>
      </RxTooltip.Portal>
    </RxTooltip.Root>
  )
}
