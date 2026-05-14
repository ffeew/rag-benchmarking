import { Outlet, createRootRouteWithContext, useLocation } from '@tanstack/react-router'

import { AppShell } from '#/components/layout/AppShell'
import type { RouterContext } from '#/router'
import { useToken } from '#/providers/TokenProvider'

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
})

function RootComponent() {
  const { pathname } = useLocation()
  const { isAuthed } = useToken()

  const isAuthRoute = pathname === '/auth'

  if (isAuthRoute || !isAuthed) {
    return <Outlet />
  }

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  )
}
