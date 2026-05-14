import * as RxTabs from '@radix-ui/react-tabs'
import type { ComponentPropsWithoutRef } from 'react'
import { forwardRef } from 'react'

import { cn } from '#/lib/cn'

export const Tabs = RxTabs.Root

export const TabsList = forwardRef<
  React.ElementRef<typeof RxTabs.List>,
  ComponentPropsWithoutRef<typeof RxTabs.List>
>(function TabsList({ className, ...props }, ref) {
  return (
    <RxTabs.List
      ref={ref}
      className={cn(
        'inline-flex items-center gap-0 border-b border-[var(--rule)]',
        className,
      )}
      {...props}
    />
  )
})

export const TabsTrigger = forwardRef<
  React.ElementRef<typeof RxTabs.Trigger>,
  ComponentPropsWithoutRef<typeof RxTabs.Trigger>
>(function TabsTrigger({ className, ...props }, ref) {
  return (
    <RxTabs.Trigger
      ref={ref}
      className={cn(
        'relative inline-flex items-center gap-1.5 px-3 h-9 text-[12.5px]',
        'mono-label text-[var(--ink-muted)] tracking-[0.06em]',
        'transition-colors hover:text-[var(--ink-dim)]',
        'data-[state=active]:text-[var(--ink)] data-[state=active]:after:content-[""] data-[state=active]:after:absolute data-[state=active]:after:left-0 data-[state=active]:after:right-0 data-[state=active]:after:-bottom-px data-[state=active]:after:h-[2px] data-[state=active]:after:bg-[var(--accent)]',
        className,
      )}
      {...props}
    />
  )
})

export const TabsContent = forwardRef<
  React.ElementRef<typeof RxTabs.Content>,
  ComponentPropsWithoutRef<typeof RxTabs.Content>
>(function TabsContent({ className, ...props }, ref) {
  return (
    <RxTabs.Content
      ref={ref}
      className={cn('mt-4 outline-none animate-fade-in', className)}
      {...props}
    />
  )
})
