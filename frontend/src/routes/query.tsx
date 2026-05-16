import { createFileRoute, useNavigate, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { ChevronsUpDown, Database, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Button } from '#/components/ui/button'
import {
  DropdownContent,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from '#/components/ui/dropdown'
import { EmptyState } from '#/components/data/EmptyState'
import { Spinner } from '#/components/ui/spinner'
import { QueryWorkspace } from '#/components/query/QueryWorkspace'
import { api } from '#/lib/api'
import type { Dataset } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import {
  paths,
  peekQueryDraft,
  readLastDataset,
  writeLastDataset,
} from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/query')({ component: QueryPage })

function pickInitialDataset(items: Array<Dataset>): string | null {
  if (items.length === 0) return null
  const draft = peekQueryDraft()
  if (draft?.dataset_id && items.some((d) => d.id === draft.dataset_id)) {
    return draft.dataset_id
  }
  const last = readLastDataset()
  if (last && items.some((d) => d.id === last)) return last
  return items[0].id
}

function QueryPage() {
  const { token, isAuthed } = useToken()
  const navigate = useNavigate()

  const datasetsQuery = useQuery({
    queryKey: qk.datasets.list({ limit: 200, offset: 0 }),
    queryFn: () => api.datasets(token, { limit: 200 }),
    enabled: isAuthed,
  })

  const items = datasetsQuery.data?.items
  const [selected, setSelected] = useState<string | null>(null)

  // Seed picker once datasets load — prefer the trace-reproduce dataset, then the
  // last-used one, then the first item. After the first seed, user picks override.
  useEffect(() => {
    if (selected !== null || !items) return
    const initial = pickInitialDataset(items)
    if (initial) {
      setSelected(initial)
      writeLastDataset(initial)
    }
  }, [items, selected])

  useEffect(() => {
    if (!isAuthed) {
      void navigate({ ...paths.auth, search: { return: paths.query.to } })
    }
  }, [isAuthed, navigate])

  const activeDataset = useMemo(
    () => items?.find((d) => d.id === selected) ?? null,
    [items, selected],
  )

  function handleSelect(id: string) {
    setSelected(id)
    writeLastDataset(id)
  }

  if (datasetsQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-[12px] text-[var(--ink-muted)]">
        <Spinner /> &nbsp;loading datasets…
      </div>
    )
  }

  if (items && items.length === 0) {
    return (
      <div className="mx-auto max-w-[1280px] px-6 py-6">
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
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6 grid gap-5">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="mono-label flex items-center gap-1.5 text-[var(--ink-muted)]">
            <Search className="h-3 w-3" />
            QUERY
          </div>
          <h1 className="mt-1 text-[24px] leading-tight font-semibold tracking-tight">
            Ask a question
          </h1>
          <p className="mt-1 text-[13px] text-[var(--ink-dim)]">
            Pick a dataset, then ask anything grounded in its ingested filings.
          </p>
        </div>

        {items && items.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="mono-label text-[var(--ink-muted)]">DATASET</span>
            <DropdownMenu>
              <DropdownTrigger asChild>
                <button
                  type="button"
                  className="inline-flex h-9 min-w-[260px] items-center gap-2 rounded-[3px] border border-[var(--rule-strong)] bg-[var(--surface)] px-3 hover:bg-[var(--surface-2)] transition-colors"
                >
                  <Database className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                  <span className="truncate text-[13px] text-[var(--ink)]">
                    {activeDataset?.name ?? 'Select dataset'}
                  </span>
                  <ChevronsUpDown className="ml-auto h-3.5 w-3.5 text-[var(--ink-muted)]" />
                </button>
              </DropdownTrigger>
              <DropdownContent align="end" className="min-w-[260px] max-h-[360px] overflow-y-auto">
                {items.map((d) => (
                  <DropdownItem key={d.id} onSelect={() => handleSelect(d.id)}>
                    <Database className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                    <span className="truncate">{d.name}</span>
                  </DropdownItem>
                ))}
              </DropdownContent>
            </DropdownMenu>
          </div>
        )}
      </header>

      {selected && <QueryWorkspace key={selected} datasetId={selected} />}
    </div>
  )
}
