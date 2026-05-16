import { Link } from '@tanstack/react-router'
import { Activity, BarChart3, Database, FileText, LayoutGrid } from 'lucide-react'
import type { ReactNode } from 'react'

import { Badge } from '#/components/ui/badge'
import { Progress } from '#/components/ui/progress'
import { MetricNumber } from '#/components/data/MetricNumber'
import type { Dataset } from '#/lib/api'
import { cn } from '#/lib/cn'
import { formatDate, formatNumber } from '#/lib/format'
import { paths } from '#/lib/routes'

type Tab = {
  build: (datasetId: string) => { to: string; params: { datasetId: string } }
  label: string
  icon: typeof LayoutGrid
  /** When true, only highlight on exact pathname match (no prefix match). */
  exact?: boolean
}

const TABS: ReadonlyArray<Tab> = [
  { build: paths.dataset, label: 'SUMMARY', icon: LayoutGrid, exact: true },
  { build: paths.datasetDocuments, label: 'DOCUMENTS', icon: FileText },
  { build: paths.datasetIngestion, label: 'INGESTION', icon: Activity },
  { build: paths.datasetEvaluations, label: 'EVALUATIONS', icon: BarChart3 },
]

function isActive(href: string, pathname: string, exact: boolean | undefined): boolean {
  if (exact) return pathname === href
  return pathname === href || pathname.startsWith(`${href}/`)
}

export function DatasetHeader({
  dataset,
  pathname,
  actions,
}: {
  dataset: Dataset
  pathname: string
  actions?: ReactNode
}) {
  const coverage =
    dataset.document_count > 0 ? dataset.completed_ingestion_count / dataset.document_count : 0
  const ready =
    dataset.document_count > 0 && dataset.completed_ingestion_count >= dataset.document_count

  return (
    <div className="border-b border-[var(--rule)] bg-[var(--surface)]">
      <div className="mx-auto max-w-[1440px] px-6 pt-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="mono-label flex items-center gap-1.5 text-[var(--ink-muted)]">
              <Database className="h-3 w-3" />
              DATASET
              <span className="font-mono text-[10.5px] text-[var(--ink-subtle)]">·</span>
              <span className="font-mono text-[10.5px] text-[var(--ink-subtle)]">
                {dataset.id.slice(0, 8)}…
              </span>
            </div>
            <h1 className="mt-1 flex items-center gap-3 text-[24px] leading-tight font-semibold tracking-tight">
              <span className="truncate">{dataset.name}</span>
              {ready && <Badge tone="ok">READY</Badge>}
            </h1>
            {dataset.description && (
              <p className="mt-1 max-w-2xl text-[13px] text-[var(--ink-dim)] truncate">
                {dataset.description}
              </p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>

        <div className="mt-5 grid grid-cols-2 gap-4 md:grid-cols-4">
          <MetricNumber label="DOCUMENTS" value={formatNumber(dataset.document_count)} size="md" />
          <MetricNumber
            label="ACTIVE CHUNKS"
            value={formatNumber(dataset.active_chunk_count)}
            size="md"
          />
          <MetricNumber
            label="INGESTION RUNS"
            value={formatNumber(dataset.completed_ingestion_count)}
            size="md"
          />
          <div className="flex flex-col gap-1.5">
            <div className="mono-label">COVERAGE</div>
            <div className="flex items-baseline gap-2">
              <span className="font-mono numeric text-[24px] font-medium leading-none">
                {Math.round(coverage * 100)}%
              </span>
            </div>
            <Progress value={coverage * 100} height={3} className="mt-1" />
          </div>
        </div>

        <nav className="mt-5 -mx-1 flex items-center gap-0 overflow-x-auto">
          {TABS.map((tab) => {
            const Icon = tab.icon
            const linkProps = tab.build(dataset.id)
            const renderedPath = linkProps.to.replace('$datasetId', dataset.id)
            const active = isActive(renderedPath, pathname, tab.exact)
            return (
              <Link
                key={tab.label}
                {...linkProps}
                className={cn(
                  'relative inline-flex items-center gap-1.5 px-3 h-10 mono-label text-[var(--ink-muted)]',
                  'transition-colors hover:text-[var(--ink-dim)]',
                  active && 'text-[var(--ink)]',
                )}
              >
                <Icon
                  className={cn(
                    'h-3.5 w-3.5',
                    active ? 'text-[var(--accent)]' : 'text-[var(--ink-muted)]',
                  )}
                />
                <span>{tab.label}</span>
                {active && (
                  <span className="absolute inset-x-2 -bottom-px h-[2px] bg-[var(--accent)]" />
                )}
              </Link>
            )
          })}
          <div className="ml-auto mr-1 font-mono text-[10.5px] text-[var(--ink-muted)] pb-2">
            created {formatDate(dataset.created_at)}
          </div>
        </nav>
      </div>
    </div>
  )
}
