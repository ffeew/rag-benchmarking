import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'

import { Overview } from '#/components/overview/Overview'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/')({ component: HomePage })

function HomePage() {
  const { isAuthed } = useToken()
  const navigate = useNavigate()

  useEffect(() => {
    if (!isAuthed) {
      void navigate({ to: '/auth' })
    }
  }, [isAuthed, navigate])

  if (!isAuthed) return null
  return <Overview />
}
