import { Toaster, toast as sonnerToast } from 'sonner'

import { useTheme } from './ThemeProvider'

export function ToastProvider() {
  const { theme } = useTheme()
  return (
    <Toaster
      theme={theme}
      position="top-right"
      richColors
      closeButton
      duration={4200}
      gap={8}
      visibleToasts={5}
      offset={20}
      toastOptions={{
        classNames: {
          toast: 'font-sans text-[13px]',
          title: 'font-medium',
          description: 'text-ink-dim',
        },
      }}
    />
  )
}

export const toast = {
  success: (message: string, description?: string) =>
    sonnerToast.success(message, { description }),
  error: (message: string, description?: string) => sonnerToast.error(message, { description }),
  info: (message: string, description?: string) => sonnerToast.message(message, { description }),
  warn: (message: string, description?: string) =>
    sonnerToast.warning(message, { description }),
  raw: sonnerToast,
}

export function toastApiError(err: unknown, fallback = 'Request failed') {
  const message = err instanceof Error ? err.message : fallback
  let title = fallback
  let description: string | undefined
  if (message.startsWith('{') || message.startsWith('[')) {
    try {
      const parsed = JSON.parse(message)
      if (parsed && typeof parsed === 'object') {
        title = String(parsed.detail ?? parsed.error ?? parsed.message ?? fallback)
      }
    } catch {
      description = message
    }
  } else if (message.length > 80) {
    description = message
  } else {
    title = message
  }
  sonnerToast.error(title, { description })
}
