import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { createRoot } from 'react-dom/client'

import { TooltipProvider } from './components/ui/tooltip'
import { ThemeProvider } from './providers/ThemeProvider'
import { TokenProvider } from './providers/TokenProvider'
import { ToastProvider } from './providers/ToastProvider'
import { getRouter } from './router'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 10_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
    },
    mutations: { retry: 0 },
  },
})

const router = getRouter(queryClient)
const app = document.getElementById('app')

if (app) {
  createRoot(app).render(
    <ThemeProvider>
      <TokenProvider>
        <QueryClientProvider client={queryClient}>
          <TooltipProvider delayDuration={250} skipDelayDuration={120}>
            <RouterProvider router={router} />
            <ToastProvider />
          </TooltipProvider>
        </QueryClientProvider>
      </TokenProvider>
    </ThemeProvider>,
  )
}
