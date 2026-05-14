import { Kbd } from '#/components/ui/kbd'

import { Breadcrumb } from './Breadcrumb'
import { DatasetSwitcher } from './DatasetSwitcher'
import { ThemeToggle } from './ThemeToggle'
import { TokenMenu } from './TokenMenu'

export function Topbar() {
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-[var(--rule)] bg-[var(--surface)] px-4">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <Breadcrumb />
      </div>
      <div className="flex items-center gap-2">
        <DatasetSwitcher />
        <span className="hidden md:inline-flex items-center gap-1 text-[10.5px] text-[var(--ink-muted)]">
          <Kbd>⌘</Kbd>
          <Kbd>K</Kbd>
        </span>
        <ThemeToggle />
        <TokenMenu />
      </div>
    </header>
  )
}
