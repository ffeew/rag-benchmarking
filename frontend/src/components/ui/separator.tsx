import * as RxSeparator from '@radix-ui/react-separator'

import { cn } from '#/lib/cn'

export function Separator({
  orientation = 'horizontal',
  className,
}: {
  orientation?: 'horizontal' | 'vertical'
  className?: string
}) {
  return (
    <RxSeparator.Root
      orientation={orientation}
      className={cn(
        'shrink-0 bg-[var(--rule)]',
        orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px',
        className,
      )}
    />
  )
}
