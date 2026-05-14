import * as RxDialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ComponentPropsWithoutRef, ReactNode } from 'react'

import { cn } from '#/lib/cn'

export const Sheet = RxDialog.Root
export const SheetTrigger = RxDialog.Trigger
export const SheetClose = RxDialog.Close

const sides = {
  right:
    'right-0 top-0 h-full w-full border-l max-w-[640px] data-[state=open]:animate-[slide-in-right_200ms_ease-out]',
  left:
    'left-0 top-0 h-full w-full border-r max-w-[480px] data-[state=open]:animate-[slide-in-right_200ms_ease-out]',
  bottom:
    'bottom-0 left-0 right-0 max-h-[80vh] border-t data-[state=open]:animate-fade-in',
} as const

export function SheetContent({
  className,
  children,
  side = 'right',
  showClose = true,
  ...props
}: ComponentPropsWithoutRef<typeof RxDialog.Content> & {
  side?: 'right' | 'left' | 'bottom'
  showClose?: boolean
}) {
  return (
    <RxDialog.Portal>
      <RxDialog.Overlay className="fixed inset-0 z-40 bg-black/45 animate-fade-in" />
      <RxDialog.Content
        className={cn(
          'fixed z-50 bg-[var(--surface)] border-[var(--rule-strong)] shadow-[var(--shadow-pop)] flex flex-col',
          sides[side],
          className,
        )}
        {...props}
      >
        {children}
        {showClose && (
          <RxDialog.Close
            className="absolute right-3 top-3 p-1 rounded-[3px] text-[var(--ink-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </RxDialog.Close>
        )}
      </RxDialog.Content>
    </RxDialog.Portal>
  )
}

export function SheetHeader({
  title,
  subtitle,
  trailing,
  className,
}: {
  title: ReactNode
  subtitle?: ReactNode
  trailing?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex items-start justify-between gap-3 px-5 pt-5 pb-3 border-b border-[var(--rule)]',
        className,
      )}
    >
      <div className="min-w-0 flex-1 pr-8">
        <RxDialog.Title className="text-[15px] font-semibold text-[var(--ink)] leading-tight truncate">
          {title}
        </RxDialog.Title>
        {subtitle && (
          <RxDialog.Description className="mt-1 text-[12.5px] text-[var(--ink-dim)] leading-tight">
            {subtitle}
          </RxDialog.Description>
        )}
      </div>
      {trailing}
    </div>
  )
}

export function SheetBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('px-5 py-4 overflow-y-auto flex-1', className)}>{children}</div>
}

export function SheetFooter({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={cn(
        'flex items-center justify-end gap-2 px-5 py-3 border-t border-[var(--rule)] bg-[var(--surface-2)]',
        className,
      )}
    >
      {children}
    </div>
  )
}
