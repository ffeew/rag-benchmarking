import * as RxCollapsible from '@radix-ui/react-collapsible'
import { ChevronRight } from 'lucide-react'
import type { ComponentPropsWithoutRef } from 'react'

import { cn } from '#/lib/cn'

export const Collapsible = RxCollapsible.Root

export function CollapsibleTrigger({
  className,
  children,
  ...props
}: ComponentPropsWithoutRef<typeof RxCollapsible.Trigger>) {
  return (
    <RxCollapsible.Trigger
      className={cn(
        'group flex w-full items-center gap-2 px-3 py-2 text-left',
        'hover:bg-[var(--surface-2)] transition-colors rounded-[3px]',
        className,
      )}
      {...props}
    >
      <ChevronRight className="h-3.5 w-3.5 text-[var(--ink-muted)] transition-transform group-data-[state=open]:rotate-90" />
      {children}
    </RxCollapsible.Trigger>
  )
}

export function CollapsibleContent({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof RxCollapsible.Content>) {
  return (
    <RxCollapsible.Content
      className={cn('animate-fade-in', className)}
      {...props}
    />
  )
}
