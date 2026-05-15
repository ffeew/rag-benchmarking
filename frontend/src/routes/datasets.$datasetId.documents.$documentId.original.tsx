import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useEffect } from 'react'

import { Skeleton } from '#/components/ui/skeleton'
import { ErrorState } from '#/components/data/ErrorState'
import { api } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute(
  '/datasets/$datasetId/documents/$documentId/original',
)({
  component: OriginalDocumentPage,
})

function OriginalDocumentPage() {
  const { documentId } = Route.useParams()
  const { token, isAuthed } = useToken()

  const blobQuery = useQuery({
    queryKey: qk.documents.file(documentId),
    queryFn: async () => {
      const blob = await api.documentFileBlob(token, documentId)
      return URL.createObjectURL(blob)
    },
    enabled: isAuthed,
    staleTime: Infinity,
    gcTime: 0,
  })

  useEffect(() => {
    const url = blobQuery.data
    return () => {
      if (url) URL.revokeObjectURL(url)
    }
  }, [blobQuery.data])

  if (!isAuthed) {
    return (
      <ErrorState
        title="Sign in required"
        description="Open this dataset in the main app first, then retry."
      />
    )
  }

  if (blobQuery.isLoading) {
    return (
      <div className="p-6">
        <Skeleton className="h-screen w-full" />
      </div>
    )
  }

  if (blobQuery.isError) {
    return (
      <ErrorState
        title="Failed to load document"
        error={blobQuery.error}
        onRetry={() => blobQuery.refetch()}
      />
    )
  }

  return (
    <iframe
      src={blobQuery.data}
      title="Original document"
      className="h-screen w-screen border-0"
    />
  )
}
