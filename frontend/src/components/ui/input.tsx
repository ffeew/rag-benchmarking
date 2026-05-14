import { forwardRef } from 'react'
import type { InputHTMLAttributes, ForwardedRef, ReactNode, TextareaHTMLAttributes, SelectHTMLAttributes } from 'react'

import { cn } from '#/lib/cn'

const inputBase =
  'h-8 w-full bg-[var(--surface)] text-[var(--ink)] placeholder:text-[var(--ink-subtle)] ' +
  'border border-[var(--rule-strong)] rounded-[3px] px-2.5 text-[13px] ' +
  'transition-colors outline-none ' +
  'hover:border-[var(--ink-muted)] focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent-ring)] focus:ring-offset-0 ' +
  'disabled:opacity-50 disabled:cursor-not-allowed'

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean
  leading?: ReactNode
  trailing?: ReactNode
}

export const Input = forwardRef(function Input(
  { className, invalid, leading, trailing, ...props }: InputProps,
  ref: ForwardedRef<HTMLInputElement>,
) {
  if (leading || trailing) {
    return (
      <div
        className={cn(
          'group relative flex h-8 items-center bg-[var(--surface)] border border-[var(--rule-strong)] rounded-[3px]',
          'transition-colors hover:border-[var(--ink-muted)] focus-within:border-[var(--accent)] focus-within:ring-2 focus-within:ring-[var(--accent-ring)]',
          invalid && 'border-[var(--bad)] focus-within:border-[var(--bad)] focus-within:ring-[var(--bad-soft)]',
          className,
        )}
      >
        {leading && <span className="pl-2 text-[var(--ink-muted)]">{leading}</span>}
        <input
          ref={ref}
          className={cn(
            'flex-1 h-full bg-transparent px-2.5 text-[13px] outline-none',
            'text-[var(--ink)] placeholder:text-[var(--ink-subtle)]',
          )}
          {...props}
        />
        {trailing && <span className="pr-2 text-[var(--ink-muted)]">{trailing}</span>}
      </div>
    )
  }
  return (
    <input
      ref={ref}
      className={cn(inputBase, invalid && 'border-[var(--bad)] focus:border-[var(--bad)] focus:ring-[var(--bad-soft)]', className)}
      {...props}
    />
  )
})

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }

export const Textarea = forwardRef(function Textarea(
  { className, invalid, ...props }: TextareaProps,
  ref: ForwardedRef<HTMLTextAreaElement>,
) {
  return (
    <textarea
      ref={ref}
      className={cn(
        'min-h-[80px] w-full bg-[var(--surface)] text-[var(--ink)] placeholder:text-[var(--ink-subtle)]',
        'border border-[var(--rule-strong)] rounded-[3px] px-2.5 py-2 text-[13px] leading-relaxed',
        'transition-colors outline-none resize-y',
        'hover:border-[var(--ink-muted)] focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent-ring)]',
        invalid && 'border-[var(--bad)] focus:border-[var(--bad)] focus:ring-[var(--bad-soft)]',
        className,
      )}
      {...props}
    />
  )
})

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }

export const Select = forwardRef(function Select(
  { className, invalid, children, ...props }: SelectProps,
  ref: ForwardedRef<HTMLSelectElement>,
) {
  return (
    <div className="relative">
      <select
        ref={ref}
        className={cn(
          'h-8 w-full appearance-none bg-[var(--surface)] text-[var(--ink)]',
          'border border-[var(--rule-strong)] rounded-[3px] pl-2.5 pr-7 text-[13px]',
          'transition-colors outline-none cursor-pointer',
          'hover:border-[var(--ink-muted)] focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent-ring)]',
          invalid && 'border-[var(--bad)]',
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <svg
        aria-hidden
        className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[var(--ink-muted)]"
        width="10"
        height="10"
        viewBox="0 0 10 10"
        fill="none"
      >
        <path d="M2 4l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  )
})
