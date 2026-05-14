import { useNavigate } from '@tanstack/react-router'
import {
  Activity,
  BarChart3,
  Database,
  FileText,
  LayoutDashboard,
  Moon,
  Search,
  Settings,
  Sun,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import { Dialog, DialogContent } from '#/components/ui/dialog'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '#/components/ui/command'
import { useTheme } from '#/providers/ThemeProvider'

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { theme, toggleTheme } = useTheme()

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function run(action: () => void) {
    setOpen(false)
    action()
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent size="md" showClose={false} className="p-0">
        <Command label="Command palette" className="bg-transparent">
          <CommandInput placeholder="Search routes, datasets, actions…" autoFocus />
          <CommandList>
            <CommandEmpty>No results.</CommandEmpty>
            <CommandGroup heading="Navigate">
              <CommandItem value="overview" onSelect={() => run(() => navigate({ to: '/' }))}>
                <LayoutDashboard className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                <span>Overview</span>
              </CommandItem>
              <CommandItem value="datasets" onSelect={() => run(() => navigate({ to: '/datasets' }))}>
                <Database className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                <span>Datasets</span>
              </CommandItem>
              <CommandItem value="query" onSelect={() => run(() => navigate({ to: '/query' }))}>
                <Search className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                <span>Query workspace</span>
              </CommandItem>
              <CommandItem value="traces" onSelect={() => run(() => navigate({ to: '/traces' }))}>
                <FileText className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                <span>Traces</span>
              </CommandItem>
              <CommandItem
                value="evaluations"
                onSelect={() => run(() => navigate({ to: '/evaluations' }))}
              >
                <BarChart3 className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                <span>Evaluations</span>
              </CommandItem>
              <CommandItem value="jobs" onSelect={() => run(() => navigate({ to: '/jobs' }))}>
                <Activity className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                <span>Jobs</span>
              </CommandItem>
              <CommandItem value="system" onSelect={() => run(() => navigate({ to: '/system' }))}>
                <Settings className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                <span>System</span>
              </CommandItem>
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Actions">
              <CommandItem
                value={`theme ${theme === 'dark' ? 'light' : 'dark'}`}
                onSelect={() => run(toggleTheme)}
              >
                {theme === 'dark' ? (
                  <Sun className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                ) : (
                  <Moon className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                )}
                <span>Switch to {theme === 'dark' ? 'light' : 'dark'} theme</span>
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  )
}
