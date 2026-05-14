import { useQuery } from '@tanstack/react-query'
import { Outlet, createFileRoute, useLocation } from '@tanstack/react-router'

import { DatasetHeader } from '#/components/datasets/DatasetHeader'
import { ErrorState } from '#/components/data/ErrorState'
import { Skeleton } from '#/components/ui/skeleton'
import { api } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import { writeLastDataset } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/datasets/$datasetId')({
  component: DatasetLayout,
})

function DatasetLayout() {
  const { datasetId } = Route.useParams()
  const { token, isAuthed } = useToken()
  const location = useLocation()

  writeLastDataset(datasetId)

  const datasetQuery = useQuery({
    queryKey: qk.datasets.detail(datasetId),
    queryFn: () => api.dataset(token, datasetId),
    enabled: isAuthed && Boolean(datasetId),
    staleTime: 10_000,
  })

  if (datasetQuery.isLoading) {
    return (
      <div className="p-6">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="mt-3 h-8 w-80" />
        <div className="mt-6 grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      </div>
    )
  }

  if (datasetQuery.isError || !datasetQuery.data) {
    return (
      <ErrorState
        title="Dataset not found"
        error={datasetQuery.error}
        onRetry={() => datasetQuery.refetch()}
      />
    )
  }

  return (
    <>
      <DatasetHeader dataset={datasetQuery.data} pathname={location.pathname} />
      <Outlet />
    </>
  )
}
