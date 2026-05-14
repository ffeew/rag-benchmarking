import { cva } from 'class-variance-authority'
import type { VariantProps } from 'class-variance-authority'
import { Slot } from '@radix-ui/react-slot'
import type {
  ButtonHTMLAttributes,
  ForwardedRef,
  ReactElement,
  ReactNode,
} from 'react'
import { Children, cloneElement, forwardRef, isValidElement } from 'react'

import { cn } from '#/lib/cn'

export const buttonStyles = cva(
  [
    'inline-flex items-center justify-center gap-1.5 whitespace-nowrap',
    'font-sans font-medium tracking-[-0.005em] transition-colors',
    'disabled:cursor-not-allowed disabled:opacity-50',
    'focus-visible:outline-2 focus-visible:outline-[var(--accent-ring)] focus-visible:outline-offset-1',
    'select-none',
  ].join(' '),
  {
    variants: {
      variant: {
        primary:
          'bg-[var(--accent)] text-[var(--bg)] hover:bg-[var(--accent-press)] border border-transparent',
        secondary:
          'bg-[var(--surface)] text-[var(--ink)] border border-[var(--rule-strong)] hover:bg-[var(--surface-2)]',
        ghost:
          'bg-transparent text-[var(--ink-dim)] hover:text-[var(--ink)] hover:bg-[var(--surface-2)] border border-transparent',
        outline:
          'bg-transparent text-[var(--ink)] border border-[var(--rule-strong)] hover:bg-[var(--surface-2)]',
        danger:
          'bg-[var(--bad)] text-white border border-transparent hover:opacity-90',
        accent:
          'bg-[var(--accent-soft)] text-[var(--accent)] border border-[var(--accent-ring)] hover:bg-[var(--accent-press)] hover:text-[var(--bg)] hover:border-transparent',
      },
      size: {
        xs: 'h-6 px-2 text-[11px] rounded-[2px]',
        sm: 'h-7 px-2.5 text-[12px] rounded-[3px]',
        md: 'h-8 px-3 text-[13px] rounded-[3px]',
        lg: 'h-10 px-4 text-[14px] rounded-[4px]',
        icon: 'h-8 w-8 rounded-[3px]',
        'icon-sm': 'h-7 w-7 rounded-[3px]',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonStyles> & {
    asChild?: boolean
    leading?: ReactNode
    trailing?: ReactNode
  }

export const Button = forwardRef(function Button(
  {
    className,
    variant,
    size,
    asChild,
    leading,
    trailing,
    children,
    ...props
  }: ButtonProps,
  ref: ForwardedRef<HTMLButtonElement>,
) {
  const classes = cn(buttonStyles({ variant, size }), className)

  if (asChild) {
    const only = Children.only(children)
    if (!isValidElement(only)) {
      throw new Error('Button: asChild requires a single React element child')
    }
    const child = only as ReactElement<{ children?: ReactNode }>
    const merged =
      leading || trailing
        ? cloneElement(
            child,
            undefined,
            leading,
            child.props.children,
            trailing,
          )
        : child
    return (
      <Slot ref={ref} className={classes} {...props}>
        {merged}
      </Slot>
    )
  }

  return (
    <button ref={ref} className={classes} {...props}>
      {leading}
      {children}
      {trailing}
    </button>
  )
})
