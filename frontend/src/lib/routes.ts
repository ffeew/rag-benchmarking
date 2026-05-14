/* Path helpers that return TanStack Router `Link` / `navigate` props.
 *
 * Each helper returns `{ to, params? }` keyed on the registered route
 * literal — letting Link/navigate type-check the destination and required
 * params end-to-end. Spread the result into the component or call:
 *
 *   <Link {...paths.dataset(id)}>Open</Link>
 *   navigate(paths.dataset(id))
 */

export const paths = {
  overview: { to: '/' },
  auth: { to: '/auth' },
  datasets: { to: '/datasets' },
  dataset: (datasetId: string) => ({
    to: '/datasets/$datasetId',
    params: { datasetId },
  }),
  datasetDocuments: (datasetId: string) => ({
    to: '/datasets/$datasetId/documents',
    params: { datasetId },
  }),
  datasetIngestion: (datasetId: string) => ({
    to: '/datasets/$datasetId/ingestion',
    params: { datasetId },
  }),
  datasetQuery: (datasetId: string) => ({
    to: '/datasets/$datasetId/query',
    params: { datasetId },
  }),
  datasetEvaluations: (datasetId: string) => ({
    to: '/datasets/$datasetId/evaluations',
    params: { datasetId },
  }),
  evaluation: (datasetId: string, evalRunId: string) => ({
    to: '/datasets/$datasetId/evaluations/$evalRunId',
    params: { datasetId, evalRunId },
  }),
  evaluationCompare: (datasetId: string, runs?: string) => ({
    to: '/datasets/$datasetId/evaluations/compare',
    params: { datasetId },
    search: { runs },
  }),
  traces: { to: '/traces' },
  trace: (traceId: string) => ({
    to: '/traces/$traceId',
    params: { traceId },
  }),
  jobs: { to: '/jobs' },
  job: (jobId: string) => ({ to: '/jobs/$jobId', params: { jobId } }),
  system: { to: '/system' },
  query: { to: '/query' },
  evaluations: { to: '/evaluations' },
} as const

export const LAST_DATASET_KEY = 'rag.lastDataset'

export function readLastDataset(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(LAST_DATASET_KEY)
  } catch {
    return null
  }
}

export function writeLastDataset(id: string | null) {
  if (typeof window === 'undefined') return
  try {
    if (id) window.localStorage.setItem(LAST_DATASET_KEY, id)
    else window.localStorage.removeItem(LAST_DATASET_KEY)
  } catch {
    /* ignore quota */
  }
}
