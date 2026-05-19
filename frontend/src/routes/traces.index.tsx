import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ScrollText, Search } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '#/components/ui/badge'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Input } from '#/components/ui/input'
import { Skeleton } from '#/components/ui/skeleton'
import { EmptyState } from '#/components/data/EmptyState'
import { ErrorState } from '#/components/data/ErrorState'
import { api } from '#/lib/api'
import { formatRelative, truncateId } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/traces/')({ component: TracesList })

function TracesList() {
  const { token, isAuthed } = useToken()
  const [search, setSearch] = useState('')

  const tracesQuery = useQuery({
    queryKey: qk.traces.list({ question: search }),
    queryFn: () => api.traces(token, { question: search || undefined, limit: 80 }),
    enabled: isAuthed,
  })

  return (
    <div className="mx-auto max-w-[1280px] px-6 py-6 grid gap-5">
      <header>
        <div className="mono-label text-[var(--ink-muted)]">QUERY TRACES</div>
        <h1 className="mt-1 text-[24px] leading-tight font-semibold tracking-tight">
          Trace archive
        </h1>
        <p className="mt-1 text-[13px] text-[var(--ink-dim)]">
          Inspect the planning, retrieval, verification, and generation steps
          for any persisted query.
        </p>
      </header>

      <Card>
        <CardHeader
          title="ALL TRACES"
          actions={
            <Input
              placeholder="Search question…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              leading={<Search className="h-3 w-3" />}
              className="h-7 w-[280px] text-[12px]"
            />
          }
        />
        <CardBody padded={false}>
          {tracesQuery.isLoading ? (
            <div className="p-4 grid gap-1.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : tracesQuery.isError ? (
            <ErrorState
              error={tracesQuery.error}
              onRetry={() => tracesQuery.refetch()}
            />
          ) : (tracesQuery.data ?? []).length === 0 ? (
            <EmptyState
              icon={ScrollText}
              title="No traces yet"
              description="Ask a question with trace persistence enabled to populate this archive."
            />
          ) : (
            <ul className="divide-y divide-[var(--rule)]">
              {(tracesQuery.data ?? []).map((t) => (
                <li key={t.id}>
                  <Link
                    {...paths.trace(t.id)}
                    className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5 hover:bg-[var(--surface-2)] transition-colors"
                  >
                    <Badge tone="cite" size="sm">
                      {t.retrieval_mode.replace('_', ' ')}
                    </Badge>
                    <div className="min-w-0">
                      <div className="text-[13px] text-[var(--ink)] truncate">
                        {t.user_question}
                      </div>
                      <div className="font-mono text-[10.5px] text-[var(--ink-muted)]">
                        {truncateId(t.id)} · {formatRelative(t.created_at)}
                      </div>
                    </div>
                    {t.confidence != null && (
                      <span className="font-mono numeric text-[11px] text-[var(--ink-dim)]">
                        {Math.round(t.confidence * 100)}%
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
