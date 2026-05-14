import { createFileRoute, useNavigate, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

import { Button } from '#/components/ui/button'
import { EmptyState } from '#/components/data/EmptyState'
import { Spinner } from '#/components/ui/spinner'
import { api } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import { paths, readLastDataset } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/query')({ component: QueryRedirect })

function QueryRedirect() {
  const { token, isAuthed } = useToken()
  const navigate = useNavigate()

  // Stop-gap: pull up to 200 datasets to populate the selector.
  const datasetsQuery = useQuery({
    queryKey: qk.datasets.list({ limit: 200, offset: 0 }),
    queryFn: () => api.datasets(token, { limit: 200 }),
    enabled: isAuthed,
  })

  const items = datasetsQuery.data?.items

  useEffect(() => {
    if (!isAuthed) {
      void navigate({ ...paths.auth, search: { return: paths.query.to } })
      return
    }
    if (items) {
      const last = readLastDataset()
      const target =
        items.find((d) => d.id === last)?.id ?? items[0]?.id
      if (target) {
        void navigate({ ...paths.datasetQuery(target), replace: true })
      }
    }
  }, [isAuthed, items, navigate])

  if (datasetsQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-[12px] text-[var(--ink-muted)]">
        <Spinner /> &nbsp;loading datasets…
      </div>
    )
  }
  if (items?.length === 0) {
    return (
      <EmptyState
        className="h-full"
        title="No datasets"
        description="Create a dataset before running queries."
        action={
          <Button asChild>
            <Link {...paths.datasets}>Manage datasets</Link>
          </Button>
        }
      />
    )
  }
  return null
}
