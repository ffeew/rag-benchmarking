import * as RxDialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ComponentPropsWithoutRef, ReactNode } from 'react'

import { cn } from '#/lib/cn'

export const Dialog = RxDialog.Root
export const DialogTrigger = RxDialog.Trigger
export const DialogClose = RxDialog.Close
export const DialogPortal = RxDialog.Portal

export function DialogOverlay({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof RxDialog.Overlay>) {
  return (
    <RxDialog.Overlay
      className={cn(
        'fixed inset-0 z-40 bg-black/45 backdrop-blur-[2px] animate-fade-in',
        className,
      )}
      {...props}
    />
  )
}

export function DialogContent({
  className,
  children,
  size = 'md',
  showClose = true,
  ...props
}: ComponentPropsWithoutRef<typeof RxDialog.Content> & {
  size?: 'sm' | 'md' | 'lg' | 'xl'
  showClose?: boolean
}) {
  const widths = { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl' }
  return (
    <DialogPortal>
      <DialogOverlay />
      <RxDialog.Content
        className={cn(
          'fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[calc(100vw-2rem)]',
          widths[size],
          'bg-[var(--surface)] border border-[var(--rule-strong)] rounded-[5px]',
          'shadow-[var(--shadow-pop)] animate-scale-in',
          'max-h-[calc(100vh-3rem)] overflow-hidden flex flex-col',
          className,
        )}
        {...props}
      >
        {children}
        {showClose && (
          <RxDialog.Close
            className="absolute right-3 top-3 p-1 rounded-[3px] text-[var(--ink-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)] transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </RxDialog.Close>
        )}
      </RxDialog.Content>
    </DialogPortal>
  )
}

export function DialogHeader({
  title,
  subtitle,
  className,
}: {
  title: ReactNode
  subtitle?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('px-5 pt-5 pb-3 border-b border-[var(--rule)]', className)}>
      <RxDialog.Title className="text-[15px] font-semibold text-[var(--ink)] leading-tight">
        {title}
      </RxDialog.Title>
      {subtitle && (
        <RxDialog.Description className="mt-1 text-[12.5px] text-[var(--ink-dim)] leading-tight">
          {subtitle}
        </RxDialog.Description>
      )}
    </div>
  )
}

export function DialogBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('px-5 py-4 overflow-y-auto flex-1', className)}>{children}</div>
}

export function DialogFooter({ className, children }: { className?: string; children: ReactNode }) {
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
