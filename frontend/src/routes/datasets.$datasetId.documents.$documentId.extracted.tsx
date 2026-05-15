import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'

import { Button } from '#/components/ui/button'
import { Skeleton } from '#/components/ui/skeleton'
import { ErrorState } from '#/components/data/ErrorState'
import { api } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute(
  '/datasets/$datasetId/documents/$documentId/extracted',
)({
  component: ExtractedDocumentPage,
})

function ExtractedDocumentPage() {
  const { datasetId, documentId } = Route.useParams()
  const { token, isAuthed } = useToken()

  const extractedQuery = useQuery({
    queryKey: qk.documents.extracted(documentId),
    queryFn: () => api.documentExtracted(token, documentId),
    enabled: isAuthed,
  })

  if (!isAuthed) {
    return (
      <ErrorState
        title="Sign in required"
        description="Open this dataset in the main app first, then retry."
      />
    )
  }

  const originalHref = `/datasets/${datasetId}/documents/${documentId}/original`
  const totalChars =
    extractedQuery.data?.pages.reduce((n, p) => n + p.text_char_count, 0) ?? 0

  return (
    <div className="mx-auto max-w-[960px] px-6 py-6">
      <header className="mb-4 flex flex-wrap items-baseline gap-3 border-b border-[var(--rule)] pb-3">
        <h1 className="font-mono text-[13px] uppercase tracking-[0.08em] text-[var(--ink)]">
          Extracted document
        </h1>
        <span className="font-mono text-[11px] text-[var(--ink-muted)]">
          {documentId.slice(0, 10)}…
        </span>
        {extractedQuery.data ? (
          <span className="font-mono text-[11px] text-[var(--ink-muted)]">
            · {extractedQuery.data.pages.length} pages ·{' '}
            {totalChars.toLocaleString()} chars
          </span>
        ) : null}
        <div className="ml-auto">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => window.open(originalHref, '_blank')}
            leading={<ExternalLink className="h-3.5 w-3.5" />}
          >
            Open original
          </Button>
        </div>
      </header>

      {extractedQuery.isLoading ? (
        <div className="grid gap-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-6" />
          ))}
        </div>
      ) : extractedQuery.isError ? (
        <ErrorState
          title="Failed to load extracted document"
          error={extractedQuery.error}
          onRetry={() => extractedQuery.refetch()}
        />
      ) : !extractedQuery.data || extractedQuery.data.pages.length === 0 ? (
        <ErrorState
          title="No extracted pages"
          description="This document has no completed ingestion run yet."
        />
      ) : (
        <article className="grid gap-6">
          {extractedQuery.data.pages.map((page) => (
            <section
              key={page.page_number}
              className="border-b border-[var(--rule)] pb-5 last:border-0"
            >
              <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--ink-muted)]">
                ## Page {page.page_number}
                {page.table_count > 0 ? (
                  <span className="ml-2 text-[var(--ink-dim)]">
                    · {page.table_count} table
                    {page.table_count === 1 ? '' : 's'}
                  </span>
                ) : null}
              </div>
              <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-[var(--ink)]">
                {page.text}
              </pre>
            </section>
          ))}
        </article>
      )}
    </div>
  )
}
