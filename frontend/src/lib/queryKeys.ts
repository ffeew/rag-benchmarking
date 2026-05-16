export type JobsListKey = {
  datasetId?: string
  jobType?: string
  status?: string
  limit: number
  offset: number
}

export type DocumentsListKey = {
  datasetId: string
  ticker?: string
  formType?: string
  ingestionStatus?: string
  q?: string
  limit: number
  offset: number
}

export type IngestionRunsListKey = {
  datasetId: string
  limit: number
  offset: number
}

export type EvaluationsListKey = {
  datasetId?: string
  limit: number
  offset: number
}

export type DatasetsListKey = { limit: number; offset: number }

export const qk = {
  ready: ['ready'] as const,
  datasets: {
    all: () => ['datasets'] as const,
    list: (p: DatasetsListKey) => ['datasets', 'list', p] as const,
    detail: (id: string) => ['datasets', 'detail', id] as const,
    documents: (p: DocumentsListKey) =>
      ['datasets', p.datasetId, 'documents', p] as const,
    documentsAll: (id: string) => ['datasets', id, 'documents'] as const,
    ingestionRunsAll: (id: string) =>
      ['datasets', id, 'ingestion-runs'] as const,
    ingestionRuns: (p: IngestionRunsListKey) =>
      ['datasets', p.datasetId, 'ingestion-runs', p] as const,
  },
  documents: {
    detail: (id: string) => ['documents', id] as const,
  },
  jobs: {
    all: () => ['jobs'] as const,
    list: (p: JobsListKey) => ['jobs', 'list', p] as const,
    detail: (id: string) => ['jobs', 'detail', id] as const,
  },
  traces: {
    all: () => ['traces'] as const,
    list: (params?: { datasetId?: string; question?: string }) =>
      [
        'traces',
        'list',
        params?.datasetId ?? 'all',
        params?.question ?? '',
      ] as const,
    detail: (id: string) => ['traces', 'detail', id] as const,
  },
  evaluations: {
    all: () => ['evaluations'] as const,
    list: (p: EvaluationsListKey) => ['evaluations', 'list', p] as const,
    detail: (id: string) => ['evaluations', 'detail', id] as const,
  },
  evalCases: {
    all: () => ['eval-cases'] as const,
    list: (
      params: {
        datasetId?: string
        category?: string
        difficulty?: string
        tag?: string
        limit?: number
        offset?: number
      } = {},
    ) => ['eval-cases', 'list', params] as const,
    detail: (id: string) => ['eval-cases', 'detail', id] as const,
  },
  evalPacks: {
    all: () => ['eval-packs'] as const,
    list: () => ['eval-packs', 'list'] as const,
  },
} as const
