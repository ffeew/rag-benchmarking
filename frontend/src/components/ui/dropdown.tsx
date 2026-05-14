import * as RxDropdown from '@radix-ui/react-dropdown-menu'
import { Check } from 'lucide-react'
import type { ComponentPropsWithoutRef, ReactNode } from 'react'

import { cn } from '#/lib/cn'

export const DropdownMenu = RxDropdown.Root
export const DropdownTrigger = RxDropdown.Trigger
export const DropdownPortal = RxDropdown.Portal
export const DropdownSub = RxDropdown.Sub
export const DropdownSubTrigger = RxDropdown.SubTrigger
export const DropdownSubContent = RxDropdown.SubContent

export function DropdownContent({
  className,
  align = 'end',
  sideOffset = 6,
  children,
  ...props
}: ComponentPropsWithoutRef<typeof RxDropdown.Content>) {
  return (
    <DropdownPortal>
      <RxDropdown.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          'z-50 min-w-[180px] py-1 rounded-[4px] animate-scale-in',
          'bg-[var(--surface)] border border-[var(--rule-strong)] shadow-[var(--shadow-pop)]',
          className,
        )}
        {...props}
      >
        {children}
      </RxDropdown.Content>
    </DropdownPortal>
  )
}

export function DropdownItem({
  className,
  inset,
  children,
  ...props
}: ComponentPropsWithoutRef<typeof RxDropdown.Item> & { inset?: boolean }) {
  return (
    <RxDropdown.Item
      className={cn(
        'relative flex items-center gap-2 px-3 py-1.5 text-[13px] cursor-pointer outline-none',
        'text-[var(--ink)] data-[highlighted]:bg-[var(--surface-2)] data-[disabled]:opacity-50 data-[disabled]:pointer-events-none',
        inset && 'pl-8',
        className,
      )}
      {...props}
    >
      {children}
    </RxDropdown.Item>
  )
}

export function DropdownCheckboxItem({
  className,
  checked,
  children,
  ...props
}: ComponentPropsWithoutRef<typeof RxDropdown.CheckboxItem>) {
  return (
    <RxDropdown.CheckboxItem
      checked={checked}
      className={cn(
        'relative flex items-center gap-2 pl-7 pr-3 py-1.5 text-[13px] cursor-pointer outline-none',
        'data-[highlighted]:bg-[var(--surface-2)]',
        className,
      )}
      {...props}
    >
      <span className="absolute left-2 inline-flex h-3 w-3 items-center justify-center">
        <RxDropdown.ItemIndicator>
          <Check className="h-3 w-3 text-[var(--accent)]" strokeWidth={3} />
        </RxDropdown.ItemIndicator>
      </span>
      {children}
    </RxDropdown.CheckboxItem>
  )
}

export function DropdownLabel({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof RxDropdown.Label>) {
  return (
    <RxDropdown.Label
      className={cn('mono-label px-3 pt-2 pb-1 select-none', className)}
      {...props}
    />
  )
}

export function DropdownSeparator({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof RxDropdown.Separator>) {
  return (
    <RxDropdown.Separator className={cn('my-1 h-px bg-[var(--rule)]', className)} {...props} />
  )
}

export function DropdownShortcut({ children }: { children: ReactNode }) {
  return (
    <span className="ml-auto pl-4 font-mono text-[10.5px] text-[var(--ink-muted)] tracking-wider">
      {children}
    </span>
  )
}
