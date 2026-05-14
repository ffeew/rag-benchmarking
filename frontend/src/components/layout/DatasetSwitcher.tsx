import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate, useParams } from '@tanstack/react-router'
import { Check, ChevronsUpDown, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from '#/components/ui/command'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '#/components/ui/popover'
import { api } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import { paths, readLastDataset, writeLastDataset } from '#/lib/routes'
import { useToken } from '#/providers/TokenProvider'

export function DatasetSwitcher() {
  const { token, isAuthed } = useToken()
  const navigate = useNavigate()
  const location = useLocation()
  const params = useParams({ strict: false })
  const datasetIdFromRoute = params.datasetId

  // Stop-gap: pull up to 200 datasets to populate the switcher dropdown.
  const datasetsQuery = useQuery({
    queryKey: qk.datasets.list({ limit: 200, offset: 0 }),
    queryFn: () => api.datasets(token, { limit: 200 }),
    enabled: isAuthed,
    staleTime: 30_000,
  })

  const datasets = datasetsQuery.data?.items ?? []
  const activeId = datasetIdFromRoute ?? readLastDataset() ?? datasets[0]?.id
  const active = datasets.find((d) => d.id === activeId)

  useEffect(() => {
    if (activeId) writeLastDataset(activeId)
  }, [activeId])

  const [open, setOpen] = useState(false)

  function switchTo(id: string) {
    setOpen(false)
    writeLastDataset(id)
    if (datasetIdFromRoute) {
      const tail = location.pathname.replace(
        `/datasets/${datasetIdFromRoute}`,
        '',
      )
      const next = `/datasets/${id}${tail}`
      void navigate({ to: next })
    } else {
      void navigate(paths.dataset(id))
    }
  }

  if (!isAuthed) return null

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Switch dataset"
          className="inline-flex h-7 items-center gap-2 rounded-[3px] border border-[var(--rule)] bg-[var(--surface)] pl-2.5 pr-1.5 hover:bg-[var(--surface-2)] transition-colors min-w-[180px]"
        >
          <span className="mono-label text-[var(--ink-muted)]">DATASET</span>
          <span className="flex-1 truncate text-left text-[12.5px] text-[var(--ink)]">
            {active?.name ?? (
              <span className="text-[var(--ink-muted)]">— select —</span>
            )}
          </span>
          <ChevronsUpDown className="h-3 w-3 text-[var(--ink-muted)]" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[320px] p-0" sideOffset={8}>
        <Command>
          <CommandInput placeholder="Search datasets…" />
          <CommandList>
            {datasets.length === 0 && (
              <CommandEmpty>No datasets — create one to start.</CommandEmpty>
            )}
            {datasets.map((d) => (
              <CommandItem
                key={d.id}
                value={`${d.name} ${d.id}`}
                onSelect={() => switchTo(d.id)}
              >
                <span className="flex h-3.5 w-3.5 items-center justify-center">
                  {active?.id === d.id && (
                    <Check className="h-3 w-3 text-[var(--accent)]" />
                  )}
                </span>
                <span className="flex-1 truncate">{d.name}</span>
                <span className="font-mono numeric text-[10.5px] text-[var(--ink-muted)]">
                  {d.document_count} docs
                </span>
              </CommandItem>
            ))}
            <div className="my-1 h-px bg-[var(--rule)]" />
            <CommandItem
              value="new dataset"
              onSelect={() => {
                setOpen(false)
                void navigate(paths.datasets)
              }}
            >
              <Plus className="h-3 w-3 text-[var(--ink-muted)]" />
              <span className="text-[var(--accent)]">New dataset</span>
            </CommandItem>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
