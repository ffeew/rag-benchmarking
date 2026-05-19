import type { ReactNode } from 'react'

import { CommandPalette } from './CommandPalette'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[var(--bg)] text-[var(--ink)]">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="flex-1 min-w-0 overflow-x-hidden overflow-y-auto">{children}</main>
      </div>
      <CommandPalette />
    </div>
  )
}
