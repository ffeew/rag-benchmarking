import { useLocation, Link } from '@tanstack/react-router'
import {
  Activity,
  BarChart3,
  Database,
  FileText,
  LayoutDashboard,
  Search,
  Settings,
  TerminalSquare,
} from 'lucide-react'
import type { ElementType, ReactNode } from 'react'

import { Kbd } from '#/components/ui/kbd'
import { cn } from '#/lib/cn'

type NavItem = {
  to: string
  label: string
  icon: ElementType
  matchPrefix?: string
  hint?: ReactNode
}

const NAV_ITEMS: ReadonlyArray<NavItem> = [
  { to: '/', label: 'OVERVIEW', icon: LayoutDashboard, matchPrefix: '/' },
  {
    to: '/datasets',
    label: 'DATASETS',
    icon: Database,
    matchPrefix: '/datasets',
  },
  { to: '/query', label: 'QUERY', icon: Search, matchPrefix: '/query' },
  { to: '/traces', label: 'TRACES', icon: FileText, matchPrefix: '/traces' },
  {
    to: '/evaluations',
    label: 'EVALS',
    icon: BarChart3,
    matchPrefix: '/evaluations',
  },
  { to: '/jobs', label: 'JOBS', icon: Activity, matchPrefix: '/jobs' },
  { to: '/system', label: 'SYSTEM', icon: Settings, matchPrefix: '/system' },
]

export function Sidebar() {
  const location = useLocation()
  const pathname = location.pathname

  return (
    <aside className="flex h-full w-[180px] shrink-0 flex-col border-r border-[var(--rule)] bg-[var(--surface)]">
      <div className="flex h-12 items-center gap-2 border-b border-[var(--rule)] px-4">
        <TerminalSquare className="h-4 w-4 text-[var(--accent)]" />
        <span className="font-mono text-[12px] font-semibold tracking-[0.14em] text-[var(--ink)]">
          FILINGS<span className="text-[var(--ink-muted)]">/</span>DESK
        </span>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 px-2 py-3">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon
          const active =
            item.to === '/'
              ? pathname === '/'
              : pathname === item.to ||
                pathname.startsWith(`${item.matchPrefix ?? item.to}/`)
          return (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                'group relative flex h-8 items-center gap-2.5 rounded-[3px] px-2.5',
                'mono-label text-[var(--ink-muted)] transition-colors',
                'hover:bg-[var(--surface-2)] hover:text-[var(--ink-dim)]',
                active && 'bg-[var(--surface-2)] text-[var(--ink)]',
              )}
            >
              {active && (
                <span className="absolute -left-2 top-1.5 bottom-1.5 w-[2px] rounded-full bg-[var(--accent)]" />
              )}
              <Icon
                className={cn(
                  'h-3.5 w-3.5 shrink-0',
                  active
                    ? 'text-[var(--accent)]'
                    : 'text-[var(--ink-muted)] group-hover:text-[var(--ink-dim)]',
                )}
              />
              <span className="flex-1">{item.label}</span>
            </Link>
          )
        })}
      </nav>

      <div className="border-t border-[var(--rule)] p-3">
        <div className="flex items-center justify-between text-[10.5px]">
          <span className="mono-label">PALETTE</span>
          <span className="inline-flex items-center gap-0.5">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
          </span>
        </div>
      </div>
    </aside>
  )
}
