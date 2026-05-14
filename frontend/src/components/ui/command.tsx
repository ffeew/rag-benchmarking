import { Command as CmdkCommand } from 'cmdk'
import { Search } from 'lucide-react'
import type { ComponentPropsWithoutRef } from 'react'

import { cn } from '#/lib/cn'

export const Command = CmdkCommand

export function CommandInput({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof CmdkCommand.Input>) {
  return (
    <div className="flex h-11 items-center gap-2 border-b border-[var(--rule)] px-3.5">
      <Search className="h-4 w-4 text-[var(--ink-muted)]" />
      <CmdkCommand.Input
        className={cn(
          'flex-1 bg-transparent outline-none text-[13px] text-[var(--ink)]',
          'placeholder:text-[var(--ink-subtle)]',
          className,
        )}
        {...props}
      />
    </div>
  )
}

export function CommandList({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof CmdkCommand.List>) {
  return (
    <CmdkCommand.List
      className={cn('max-h-[60vh] overflow-y-auto overflow-x-hidden p-1', className)}
      {...props}
    />
  )
}

export function CommandEmpty({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof CmdkCommand.Empty>) {
  return (
    <CmdkCommand.Empty
      className={cn('py-8 text-center text-[12.5px] text-[var(--ink-muted)]', className)}
      {...props}
    />
  )
}

export function CommandGroup({
  className,
  heading,
  ...props
}: ComponentPropsWithoutRef<typeof CmdkCommand.Group>) {
  return (
    <CmdkCommand.Group
      heading={heading}
      className={cn(
        'mb-1 [&_[cmdk-group-heading]]:mono-label [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1',
        className,
      )}
      {...props}
    />
  )
}

export function CommandItem({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof CmdkCommand.Item>) {
  return (
    <CmdkCommand.Item
      className={cn(
        'flex items-center gap-2.5 px-3 py-2 rounded-[3px] cursor-pointer outline-none',
        'text-[13px] text-[var(--ink)]',
        'data-[selected=true]:bg-[var(--surface-2)] data-[selected=true]:text-[var(--ink)]',
        className,
      )}
      {...props}
    />
  )
}

export function CommandSeparator({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof CmdkCommand.Separator>) {
  return (
    <CmdkCommand.Separator className={cn('my-1 h-px bg-[var(--rule)]', className)} {...props} />
  )
}
