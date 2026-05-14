import { Moon, Sun } from 'lucide-react'

import { Tooltip } from '#/components/ui/tooltip'
import { useTheme } from '#/providers/ThemeProvider'

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  return (
    <Tooltip content={theme === 'dark' ? 'Light theme' : 'Dark theme'}>
      <button
        type="button"
        onClick={toggleTheme}
        className="inline-flex h-7 w-7 items-center justify-center rounded-[3px] text-[var(--ink-dim)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)] transition-colors"
        aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      >
        {theme === 'dark' ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
      </button>
    </Tooltip>
  )
}
