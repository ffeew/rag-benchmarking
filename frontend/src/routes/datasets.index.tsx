import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Database, FolderInput } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '#/components/ui/badge'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Pagination } from '#/components/ui/pagination'
import { Progress } from '#/components/ui/progress'
import { Skeleton } from '#/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '#/components/ui/table'
import { EmptyState } from '#/components/data/EmptyState'
import { ErrorState } from '#/components/data/ErrorState'
import { NewDatasetDialog } from '#/components/datasets/NewDatasetDialog'
import { api } from '#/lib/api'
import { formatDate, formatNumber } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/datasets/')({ component: DatasetsList })

function DatasetsList() {
  const { token, isAuthed } = useToken()
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const datasetsQuery = useQuery({
    queryKey: qk.datasets.list({ limit, offset }),
    queryFn: () => api.datasets(token, { limit, offset }),
    enabled: isAuthed,
    placeholderData: keepPreviousData,
  })

  const items = datasetsQuery.data?.items ?? []
  const total = datasetsQuery.data?.total ?? 0

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-5 px-6 py-6">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mono-label text-[var(--ink-muted)]">CATALOG</div>
          <h1 className="mt-1 text-[24px] leading-tight font-semibold tracking-tight">
            Datasets
          </h1>
          <p className="mt-1 text-[13px] text-[var(--ink-dim)]">
            One namespace per corpus of filings — each owns its documents,
            ingestion runs, and evaluation history.
          </p>
        </div>
        <NewDatasetDialog />
      </header>

      <Card>
        <CardHeader title="ALL DATASETS" />
        <CardBody padded={false}>
          {datasetsQuery.isLoading ? (
            <div className="p-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="mb-1.5 h-7" />
              ))}
            </div>
          ) : datasetsQuery.isError ? (
            <ErrorState
              error={datasetsQuery.error}
              onRetry={() => datasetsQuery.refetch()}
            />
          ) : items.length === 0 ? (
            <EmptyState
              icon={Database}
              title="No datasets yet"
              description="Create an empty dataset to upload PDFs, or import the bundled SEC filings corpus from disk."
              action={
                <div className="flex items-center gap-2">
                  <NewDatasetDialog
                    trigger={
                      <button className="inline-flex h-8 items-center gap-1.5 rounded-[3px] border border-[var(--rule-strong)] px-3 text-[12.5px] hover:bg-[var(--surface-2)]">
                        <FolderInput className="h-3.5 w-3.5" /> Import corpus
                      </button>
                    }
                  />
                </div>
              }
            />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>NAME</TH>
                  <TH>DOCUMENTS</TH>
                  <TH>CHUNKS</TH>
                  <TH>INGESTED</TH>
                  <TH>CREATED</TH>
                </tr>
              </THead>
              <TBody>
                {items.map((d) => {
                  const coverage =
                    d.document_count > 0
                      ? d.completed_ingestion_count / d.document_count
                      : 0
                  return (
                    <TR key={d.id} interactive className="group">
                      <TD>
                        <Link
                          {...paths.dataset(d.id)}
                          className="block min-w-0"
                        >
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-[var(--ink)] group-hover:text-[var(--accent)] transition-colors">
                              {d.name}
                            </span>
                            {d.document_count > 0 &&
                              d.completed_ingestion_count >=
                                d.document_count && (
                                <Badge tone="ok" size="sm">
                                  ready
                                </Badge>
                              )}
                          </div>
                          {d.description && (
                            <div className="text-[11.5px] text-[var(--ink-muted)] mt-0.5 truncate max-w-md">
                              {d.description}
                            </div>
                          )}
                          <div className="font-mono text-[10.5px] text-[var(--ink-muted)] mt-0.5">
                            {d.id.slice(0, 12)}…
                          </div>
                        </Link>
                      </TD>
                      <TD numeric>{formatNumber(d.document_count)}</TD>
                      <TD numeric>{formatNumber(d.active_chunk_count)}</TD>
                      <TD>
                        <div className="flex items-center gap-2 min-w-[140px]">
                          <Progress value={coverage * 100} className="flex-1" />
                          <span className="font-mono numeric text-[11px] text-[var(--ink-dim)] min-w-[42px] text-right">
                            {Math.round(coverage * 100)}%
                          </span>
                        </div>
                      </TD>
                      <TD>
                        <span className="font-mono text-[11px] text-[var(--ink-muted)]">
                          {formatDate(d.created_at)}
                        </span>
                      </TD>
                    </TR>
                  )
                })}
              </TBody>
            </Table>
          )}
          <Pagination
            total={total}
            limit={limit}
            offset={offset}
            onChange={({ limit: nextLimit, offset: nextOffset }) => {
              setLimit(nextLimit)
              setOffset(nextOffset)
            }}
          />
        </CardBody>
      </Card>
    </div>
  )
}
