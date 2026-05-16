import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import {
  CheckSquare,
  Database,
  FileSearch,
  FileText,
  MoreHorizontal,
  Play,
  RefreshCcw,
  Square,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import {
  DropdownContent,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from '#/components/ui/dropdown'
import { Input, Select } from '#/components/ui/input'
import { Pagination } from '#/components/ui/pagination'
import { Skeleton } from '#/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '#/components/ui/table'
import { Tooltip } from '#/components/ui/tooltip'
import { Chip } from '#/components/data/Chip'
import { EmptyState } from '#/components/data/EmptyState'
import { ErrorState } from '#/components/data/ErrorState'
import { DocumentDrawer } from '#/components/documents/DocumentDrawer'
import { UploadSheet } from '#/components/documents/UploadSheet'
import { api } from '#/lib/api'
import type { Document } from '#/lib/api'
import { formatBytes, formatDate } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { toast, toastApiError } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/datasets/$datasetId/documents')({
  component: DocumentsPage,
})

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(handle)
  }, [value, delayMs])
  return debounced
}

function DocumentsPage() {
  const { datasetId } = Route.useParams()
  const { token, isAuthed } = useToken()
  const queryClient = useQueryClient()

  const [activeDoc, setActiveDoc] = useState<Document | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const [tickerFilter, setTickerFilter] = useState('')
  const [formFilter, setFormFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, 300)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    setOffset(0)
  }, [tickerFilter, formFilter, statusFilter, debouncedSearch, limit])

  const documentsQuery = useQuery({
    queryKey: qk.datasets.documents({
      datasetId,
      ticker: tickerFilter || undefined,
      formType: formFilter || undefined,
      ingestionStatus: statusFilter || undefined,
      q: debouncedSearch || undefined,
      limit,
      offset,
    }),
    queryFn: () =>
      api.documents(token, datasetId, {
        ticker: tickerFilter || undefined,
        form_type: formFilter || undefined,
        ingestion_status: statusFilter || undefined,
        q: debouncedSearch || undefined,
        limit,
        offset,
      }),
    enabled: isAuthed,
    placeholderData: keepPreviousData,
  })

  const items = documentsQuery.data?.items ?? []
  const total = documentsQuery.data?.total ?? 0

  // Dropdown facets are derived from the current page only — paginated data
  // cannot enumerate every distinct value in the dataset. Acceptable for v1;
  // a /facets endpoint is a separate follow-up.
  const tickers = Array.from(new Set(items.map((d) => d.ticker))).sort()
  const forms = Array.from(new Set(items.map((d) => d.form_type))).sort()
  const statuses = Array.from(
    new Set(items.map((d) => d.ingestion_status ?? 'new')),
  ).sort()

  const ingest = useMutation({
    mutationFn: (force: boolean) =>
      api.ingest(token, datasetId, {
        force,
        document_ids: selected.size > 0 ? Array.from(selected) : undefined,
      }),
    onSuccess: (result) => {
      toast.success(
        `Queued ${result.queued_document_ids.length} job${result.queued_document_ids.length === 1 ? '' : 's'}`,
        result.skipped_document_ids.length > 0
          ? `${result.skipped_document_ids.length} already up to date`
          : undefined,
      )
      setSelected(new Set())
      void queryClient.invalidateQueries({ queryKey: qk.datasets.all() })
      void queryClient.invalidateQueries({
        queryKey: qk.datasets.documentsAll(datasetId),
      })
      void queryClient.invalidateQueries({ queryKey: qk.jobs.all() })
    },
    onError: (err) => toastApiError(err, 'Failed to queue ingestion'),
  })

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  function toggleAllOnPage() {
    setSelected((prev) => {
      const allOnPageSelected =
        items.length > 0 && items.every((d) => prev.has(d.id))
      const next = new Set(prev)
      if (allOnPageSelected) {
        items.forEach((d) => next.delete(d.id))
      } else {
        items.forEach((d) => next.add(d.id))
      }
      return next
    })
  }

  const allOnPageSelected =
    items.length > 0 && items.every((d) => selected.has(d.id))

  const hasFilter = Boolean(
    tickerFilter || formFilter || statusFilter || search,
  )

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6">
      <Card>
        <CardHeader
          title={
            <span>
              DOCUMENTS{' '}
              <span className="font-mono numeric text-[var(--ink-muted)]">
                · {items.length}/{total}
              </span>
            </span>
          }
          actions={
            <div className="flex items-center gap-2">
              <Tooltip content="Ingest only documents without an active run">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={ingest.isPending}
                  onClick={() => ingest.mutate(false)}
                  leading={<Play className="h-3.5 w-3.5" />}
                >
                  Ingest{' '}
                  {selected.size > 0
                    ? `selected (${selected.size})`
                    : 'missing'}
                </Button>
              </Tooltip>
              <Tooltip content="Force re-ingestion regardless of state">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={ingest.isPending}
                  onClick={() => ingest.mutate(true)}
                  leading={<RefreshCcw className="h-3.5 w-3.5" />}
                >
                  Reindex {selected.size > 0 ? `(${selected.size})` : 'all'}
                </Button>
              </Tooltip>
              <UploadSheet datasetId={datasetId} />
            </div>
          }
        />
        <CardBody padded={false}>
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2 border-b border-[var(--rule)] px-4 py-2.5">
            <Input
              placeholder="Search ticker, company, key…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-7 w-[260px] text-[12px]"
            />
            <Select
              value={tickerFilter}
              onChange={(e) => setTickerFilter(e.target.value)}
              className="h-7 w-[160px] text-[12px]"
            >
              <option value="">All tickers</option>
              {tickers.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
            <Select
              value={formFilter}
              onChange={(e) => setFormFilter(e.target.value)}
              className="h-7 w-[130px] text-[12px]"
            >
              <option value="">All forms</option>
              {forms.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
            <Select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="h-7 w-[150px] text-[12px]"
            >
              <option value="">All statuses</option>
              {statuses.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
            {hasFilter && (
              <Button
                variant="ghost"
                size="xs"
                onClick={() => {
                  setSearch('')
                  setTickerFilter('')
                  setFormFilter('')
                  setStatusFilter('')
                }}
                leading={<X className="h-3 w-3" />}
              >
                clear
              </Button>
            )}
            <div className="ml-auto flex items-center gap-2 font-mono text-[10.5px] text-[var(--ink-muted)]">
              {selected.size > 0 ? (
                <Chip
                  tone="accent"
                  size="sm"
                  onRemove={() => setSelected(new Set())}
                >
                  {selected.size} selected
                </Chip>
              ) : null}
            </div>
          </div>

          {/* Body */}
          {documentsQuery.isLoading ? (
            <div className="p-4 grid gap-1.5">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-7" />
              ))}
            </div>
          ) : documentsQuery.isError ? (
            <ErrorState
              error={documentsQuery.error}
              onRetry={() => documentsQuery.refetch()}
            />
          ) : total === 0 && !hasFilter ? (
            <EmptyState
              icon={Database}
              title="No documents yet"
              description="Upload PDFs or run the bulk corpus import."
              action={<UploadSheet datasetId={datasetId} />}
            />
          ) : items.length === 0 ? (
            <EmptyState
              title="No documents match your filters"
              description="Try clearing the search or filter set above."
            />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH className="w-8">
                    <Tooltip content="Toggle selection for current page">
                      <button
                        type="button"
                        aria-label="Toggle current page"
                        onClick={toggleAllOnPage}
                        className="inline-flex items-center justify-center text-[var(--ink-muted)] hover:text-[var(--ink)]"
                      >
                        {allOnPageSelected ? (
                          <CheckSquare className="h-3.5 w-3.5 text-[var(--accent)]" />
                        ) : (
                          <Square className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </Tooltip>
                  </TH>
                  <TH>TICKER</TH>
                  <TH>COMPANY</TH>
                  <TH>FORM</TH>
                  <TH>FISCAL</TH>
                  <TH>FILED</TH>
                  <TH>STATUS</TH>
                  <TH>SIZE</TH>
                  <TH>OBJECT</TH>
                  <TH className="w-8" />
                </tr>
              </THead>
              <TBody>
                {items.map((d) => {
                  const isSelected = selected.has(d.id)
                  return (
                    <TR
                      key={d.id}
                      interactive
                      selected={isSelected}
                      onClick={() => {
                        setActiveDoc(d)
                        setDrawerOpen(true)
                      }}
                    >
                      <TD onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          aria-label="Toggle"
                          onClick={() => toggle(d.id)}
                          className="text-[var(--ink-muted)] hover:text-[var(--ink)]"
                        >
                          {isSelected ? (
                            <CheckSquare className="h-3.5 w-3.5 text-[var(--accent)]" />
                          ) : (
                            <Square className="h-3.5 w-3.5" />
                          )}
                        </button>
                      </TD>
                      <TD>
                        <span className="font-mono font-medium text-[var(--ink)]">
                          {d.ticker}
                        </span>
                      </TD>
                      <TD className="text-[var(--ink-dim)] max-w-[220px] truncate">
                        {d.company_name ?? '–'}
                      </TD>
                      <TD>
                        <Badge tone="neutral" size="sm">
                          {d.form_type}
                        </Badge>
                      </TD>
                      <TD className="font-mono text-[11.5px] text-[var(--ink-dim)]">
                        {d.fiscal_year ?? '–'}
                        {d.fiscal_quarter ? ` Q${d.fiscal_quarter}` : ''}
                      </TD>
                      <TD className="font-mono text-[11.5px] text-[var(--ink-dim)]">
                        {formatDate(d.filing_date)}
                      </TD>
                      <TD>
                        <Badge
                          tone={toneForStatus(d.ingestion_status)}
                          size="sm"
                        >
                          {d.ingestion_status ?? 'new'}
                        </Badge>
                      </TD>
                      <TD numeric className="text-[var(--ink-muted)]">
                        {formatBytes(d.byte_size)}
                      </TD>
                      <TD className="max-w-[280px] truncate font-mono text-[10.5px] text-[var(--ink-muted)]">
                        {d.minio_key}
                      </TD>
                      <TD onClick={(e) => e.stopPropagation()}>
                        <DocumentRowMenu documentId={d.id} />
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

      <DocumentDrawer
        document={activeDoc}
        open={drawerOpen}
        onOpenChange={(o) => {
          setDrawerOpen(o)
          if (!o) setActiveDoc(null)
        }}
      />
    </div>
  )
}

function DocumentRowMenu({ documentId }: { documentId: string }) {
  const { token } = useToken()
  const openMutation = useMutation({
    mutationFn: (kind: 'original' | 'extracted') =>
      kind === 'original'
        ? api.documentFilePresignedUrl(token, documentId)
        : api.documentExtractedPresignedUrl(token, documentId),
    onSuccess: ({ url }) => {
      window.open(url, '_blank', 'noopener,noreferrer')
    },
    onError: (err) => toastApiError(err, 'Failed to open document'),
  })
  const inflight = openMutation.isPending
  return (
    <DropdownMenu>
      <DropdownTrigger asChild>
        <button
          type="button"
          aria-label="Open document menu"
          className="inline-flex h-5 w-5 items-center justify-center rounded-[3px] text-[var(--ink-muted)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownItem
          disabled={inflight}
          onSelect={() => openMutation.mutate('original')}
        >
          <FileText className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
          View original document
        </DropdownItem>
        <DropdownItem
          disabled={inflight}
          onSelect={() => openMutation.mutate('extracted')}
        >
          <FileSearch className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
          View extracted document
        </DropdownItem>
      </DropdownContent>
    </DropdownMenu>
  )
}
