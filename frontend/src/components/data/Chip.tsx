import { X } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '#/lib/cn'

export function Chip({
  children,
  onRemove,
  tone = 'neutral',
  className,
  size = 'md',
}: {
  children: ReactNode
  onRemove?: () => void
  tone?: 'neutral' | 'accent' | 'cite'
  className?: string
  size?: 'sm' | 'md'
}) {
  const tones = {
    neutral: 'bg-[var(--surface-2)] border-[var(--rule-strong)] text-[var(--ink)]',
    accent: 'bg-[var(--accent-soft)] border-[var(--accent-ring)] text-[var(--accent)]',
    cite: 'bg-[var(--cite-soft)] border-[var(--cite)]/30 text-[var(--cite)]',
  }
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-[2px] border font-mono',
        size === 'sm' ? 'h-5 px-1.5 text-[10.5px]' : 'h-6 px-2 text-[11.5px]',
        tones[tone],
        className,
      )}
    >
      {children}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove"
          className="ml-0.5 -mr-1 inline-flex h-3.5 w-3.5 items-center justify-center rounded-[2px] hover:bg-black/10 dark:hover:bg-white/10"
        >
          <X className="h-2.5 w-2.5" />
        </button>
      )}
    </span>
  )
}
