import { Outlet, createRootRouteWithContext, useLocation } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'

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
    return (
      <>
        <Outlet />
        <DevTools />
      </>
    )
  }

  return (
    <>
      <AppShell>
        <Outlet />
      </AppShell>
      <DevTools />
    </>
  )
}

function DevTools() {
  if (!import.meta.env.DEV) return null
  return (
    <>
      <TanStackRouterDevtools position="bottom-right" />
      <ReactQueryDevtools buttonPosition="bottom-left" />
    </>
  )
}
