import * as RxToggleGroup from '@radix-ui/react-toggle-group'
import type { ReactNode } from 'react'

import { cn } from '#/lib/cn'

export type SegmentedOption<T extends string> = {
  value: T
  label: ReactNode
  description?: ReactNode
  hint?: ReactNode
}

export function Segmented<T extends string>({
  value,
  onValueChange,
  options,
  className,
  size = 'md',
  disabled,
}: {
  value: T
  onValueChange: (value: T) => void
  options: ReadonlyArray<SegmentedOption<T>>
  className?: string
  size?: 'sm' | 'md'
  disabled?: boolean
}) {
  const heights = { sm: 'h-7', md: 'h-8' }
  const padding = { sm: 'px-2.5 text-[11.5px]', md: 'px-3 text-[12.5px]' }
  return (
    <RxToggleGroup.Root
      type="single"
      value={value}
      onValueChange={(next) => next && onValueChange(next as T)}
      disabled={disabled}
      className={cn(
        'inline-flex items-stretch rounded-[3px] bg-[var(--surface-2)] border border-[var(--rule)]',
        'p-0.5 gap-0.5',
        className,
      )}
    >
      {options.map((option) => (
        <RxToggleGroup.Item
          key={option.value}
          value={option.value}
          title={typeof option.description === 'string' ? option.description : undefined}
          className={cn(
            'inline-flex items-center justify-center gap-1.5 rounded-[2px] font-medium transition-colors',
            heights[size],
            padding[size],
            'text-[var(--ink-dim)] hover:text-[var(--ink)]',
            'data-[state=on]:bg-[var(--surface)] data-[state=on]:text-[var(--ink)] data-[state=on]:shadow-sm',
            'data-[state=on]:border data-[state=on]:border-[var(--rule-strong)]',
          )}
        >
          {option.label}
          {option.hint && (
            <span className="font-mono text-[10px] text-[var(--ink-muted)]">{option.hint}</span>
          )}
        </RxToggleGroup.Item>
      ))}
    </RxToggleGroup.Root>
  )
}
