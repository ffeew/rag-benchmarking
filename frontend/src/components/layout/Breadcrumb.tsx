import { Link, useMatches } from '@tanstack/react-router'
import { ChevronRight } from 'lucide-react'
import { Fragment } from 'react'

import { cn } from '#/lib/cn'

type Crumb = { label: string; to?: string; mono?: boolean }

function pathToCrumbs(pathname: string): Array<Crumb> {
  const out: Array<Crumb> = []
  const segments = pathname.split('/').filter(Boolean)
  if (segments.length === 0) {
    return [{ label: 'overview' }]
  }
  const labelMap: Record<string, string> = {
    datasets: 'datasets',
    documents: 'documents',
    ingestion: 'ingestion',
    query: 'query',
    evaluations: 'evaluations',
    compare: 'compare',
    traces: 'traces',
    jobs: 'jobs',
    system: 'system',
    auth: 'auth',
  }
  let acc = ''
  segments.forEach((seg, i) => {
    acc += `/${seg}`
    if (labelMap[seg]) {
      out.push({ label: labelMap[seg], to: acc })
    } else if (/^[0-9a-f-]{6,}$/i.test(seg)) {
      out.push({ label: `${seg.slice(0, 6)}…`, to: acc, mono: true })
    } else {
      out.push({ label: seg, to: acc, mono: i > 0 })
    }
  })
  return out
}

export function Breadcrumb() {
  const matches = useMatches()
  const pathname = matches[matches.length - 1].pathname
  const crumbs = pathToCrumbs(pathname)

  return (
    <nav
      aria-label="Breadcrumb"
      className="flex min-w-0 items-center gap-1.5 text-[12px]"
    >
      {crumbs.map((crumb, idx) => {
        const isLast = idx === crumbs.length - 1
        return (
          <Fragment key={`${crumb.label}-${idx}`}>
            {idx > 0 && (
              <ChevronRight className="h-3 w-3 text-[var(--ink-muted)]" />
            )}
            {crumb.to && !isLast ? (
              <Link
                to={crumb.to}
                className={cn(
                  'truncate text-[var(--ink-muted)] hover:text-[var(--ink)] transition-colors',
                  crumb.mono && 'font-mono',
                )}
              >
                {crumb.label}
              </Link>
            ) : (
              <span
                className={cn(
                  'truncate text-[var(--ink)]',
                  crumb.mono && 'font-mono',
                )}
              >
                {crumb.label}
              </span>
            )}
          </Fragment>
        )
      })}
    </nav>
  )
}
