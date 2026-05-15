import { z } from 'zod'

/* ─── Zod schemas ───────────────────────────────────────────────────── */

export const datasetSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  default_query_settings: z.record(z.string(), z.unknown()),
  created_at: z.string(),
  document_count: z.number(),
  active_chunk_count: z.number(),
  completed_ingestion_count: z.number(),
})

export const documentSchema = z.object({
  id: z.string(),
  dataset_id: z.string(),
  ticker: z.string(),
  company_name: z.string().nullable(),
  form_type: z.string(),
  filing_date: z.string().nullable(),
  report_period: z.string().nullable(),
  fiscal_year: z.number().nullable(),
  fiscal_quarter: z.number().nullable(),
  checksum: z.string(),
  minio_bucket: z.string(),
  minio_key: z.string(),
  minio_version_id: z.string().nullable(),
  byte_size: z.number(),
  active_ingestion_run_id: z.string().nullable(),
  ingestion_status: z.string().nullable(),
  created_at: z.string(),
})

export const documentExtractedSchema = z.object({
  document_id: z.string(),
  ingestion_run_id: z.string(),
  pages: z.array(
    z.object({
      page_number: z.number(),
      text: z.string(),
      text_char_count: z.number(),
      table_count: z.number(),
    }),
  ),
})

export type DocumentExtracted = z.output<typeof documentExtractedSchema>

export const jobSchema = z.object({
  id: z.string(),
  job_type: z.string(),
  status: z.string(),
  progress: z.number(),
  current_step: z.string().nullable(),
  dataset_id: z.string().nullable(),
  document_id: z.string().nullable(),
  eval_run_id: z.string().nullable(),
  error: z.string().nullable(),
  metadata: z.record(z.string(), z.unknown()),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  last_heartbeat_at: z.string().nullable(),
  retry_count: z.number(),
  created_at: z.string(),
})

export const jobSweepResponseSchema = z.object({
  redispatched: z.number(),
  exhausted: z.number(),
  reaped: z.number(),
})

export const citationSchema = z.object({
  document_id: z.string(),
  ticker: z.string(),
  form_type: z.string(),
  filing_date: z.string().nullable(),
  report_period: z.string().nullable(),
  page_number: z.number(),
  chunk_id: z.string(),
  minio_bucket: z.string(),
  minio_key: z.string(),
  minio_version_id: z.string().nullable(),
  snippet: z.string(),
  label: z.string(),
})

export const evidenceSchema = z.object({
  chunk_id: z.string(),
  document_id: z.string(),
  ticker: z.string(),
  form_type: z.string(),
  filing_date: z.string().nullable(),
  page_start: z.number(),
  page_end: z.number(),
  contains_table: z.boolean(),
  score: z.number(),
  snippet: z.string(),
})

export const queryResponseSchema = z.object({
  answer: z.string(),
  citations: z.array(citationSchema),
  evidence: z.array(evidenceSchema),
  trace_id: z.string(),
  confidence: z.number(),
  insufficiency_reason: z.string().nullable(),
})

export const traceSchema = z.object({
  id: z.string(),
  dataset_id: z.string(),
  user_question: z.string(),
  retrieval_mode: z.string(),
  plan: z.record(z.string(), z.unknown()),
  retrieval_calls: z.array(z.record(z.string(), z.unknown())),
  verifier_result: z.record(z.string(), z.unknown()),
  model_metadata: z.record(z.string(), z.unknown()),
  final_answer_metadata: z.record(z.string(), z.unknown()),
  timings: z.record(z.string(), z.unknown()),
  citations: z.array(citationSchema),
  created_at: z.string(),
})

export const traceSummarySchema = z.object({
  id: z.string(),
  dataset_id: z.string(),
  user_question: z.string(),
  retrieval_mode: z.string(),
  confidence: z.number().nullable(),
  created_at: z.string(),
})

export const evalResultSchema = z.object({
  id: z.string(),
  eval_case_id: z.string().nullable(),
  retrieval_mode: z.string(),
  answer: z.string().nullable(),
  trace_id: z.string().nullable(),
  metrics: z.record(z.string(), z.unknown()),
  error: z.string().nullable(),
  usage: z.record(z.string(), z.unknown()).nullable().optional(),
  cost_estimate: z.record(z.string(), z.unknown()).nullable().optional(),
  latency_ms: z.number().nullable().optional(),
})

export const evalRunSchema = z.object({
  id: z.string(),
  dataset_id: z.string(),
  job_id: z.string().nullable(),
  status: z.string(),
  run_config: z.record(z.string(), z.unknown()),
  system_variant: z.string(),
  model_metadata: z.record(z.string(), z.unknown()),
  metrics: z.record(z.string(), z.unknown()),
  errors: z.array(z.record(z.string(), z.unknown())),
  results: z.array(evalResultSchema),
  created_at: z.string(),
})

export const expectedValueSchema = z.object({
  label: z.string(),
  value_numeric: z.number().nullable().optional(),
  value_text: z.string().nullable().optional(),
  unit: z.string().nullable().optional(),
  tolerance_abs: z.number().nullable().optional(),
  tolerance_pct: z.number().nullable().optional(),
})

export const expectedAnswerSpecSchema = z.object({
  answer_type: z
    .enum(['numeric', 'text', 'multi_part', 'insufficient', 'refusal'])
    .nullable()
    .optional(),
  expected_values: z.array(expectedValueSchema).default([]),
  required_claims: z.array(z.string()).default([]),
  required_reason_keywords: z.array(z.string()).default([]),
})

export const expectedEvidenceSchema = z.object({
  ticker: z.string().nullable().optional(),
  form_type: z.string().nullable().optional(),
  document_id: z.string().nullable().optional(),
  filing_date: z.string().nullable().optional(),
  report_period: z.string().nullable().optional(),
  page_number: z.number().nullable().optional(),
  evidence_text: z.string().nullable().optional(),
  evidence_hash: z.string().nullable().optional(),
  table_key: z.string().nullable().optional(),
})

export const evalCaseSchema = z.object({
  id: z.string(),
  dataset_id: z.string().nullable(),
  case_key: z.string().nullable().optional(),
  category: z.string().nullable().optional(),
  difficulty: z.string().nullable().optional(),
  question: z.string(),
  expected_answer: z.string().nullable(),
  expected_citations: z.array(z.record(z.string(), z.unknown())),
  expected_answer_spec: expectedAnswerSpecSchema.default({
    expected_values: [],
    required_claims: [],
    required_reason_keywords: [],
  }),
  expected_evidence: z.array(expectedEvidenceSchema).default([]),
  verification_status: z.string().default('draft'),
  verified_by: z.string().nullable().default(null),
  verified_at: z.string().nullable().default(null),
  gold_version: z.string().default('v1'),
  tags: z.array(z.string()),
  created_at: z.string(),
  updated_at: z.string().optional(),
})

export const ingestionRunSchema = z.object({
  id: z.string(),
  dataset_id: z.string(),
  document_id: z.string(),
  job_id: z.string().nullable(),
  parser_config: z.record(z.string(), z.unknown()),
  chunking_config: z.record(z.string(), z.unknown()),
  embedding_model: z.string().nullable(),
  status: z.string(),
  timings: z.record(z.string(), z.unknown()),
  counts: z.record(z.string(), z.unknown()),
  error_summary: z.string().nullable(),
  created_at: z.string(),
})

export const readySchema = z.object({
  status: z.string(),
  database: z.boolean(),
  minio: z.boolean(),
  redis: z.boolean(),
  providers: z.record(z.string(), z.unknown()),
})

export type Dataset = z.infer<typeof datasetSchema>
export type Document = z.infer<typeof documentSchema>
export type Job = z.infer<typeof jobSchema>
export type Citation = z.infer<typeof citationSchema>
export type Evidence = z.infer<typeof evidenceSchema>
export type QueryResponse = z.infer<typeof queryResponseSchema>
export type Trace = z.infer<typeof traceSchema>
export type TraceSummary = z.infer<typeof traceSummarySchema>
export type EvalRun = z.infer<typeof evalRunSchema>
export type EvalResult = z.infer<typeof evalResultSchema>
export type EvalCase = z.infer<typeof evalCaseSchema>
export type IngestionRun = z.infer<typeof ingestionRunSchema>
export type ReadyStatus = z.infer<typeof readySchema>

export type RetrievalMode = 'full_agentic' | 'single_pass' | 'llm_only'

export const RETRIEVAL_MODES = [
  'full_agentic',
  'single_pass',
  'llm_only',
] as const

export type QueryFilters = {
  ticker?: Array<string>
  form_type?: Array<string>
  filing_date_start?: string
  filing_date_end?: string
  report_period_start?: string
  report_period_end?: string
  document_ids?: Array<string>
}

export type QueryRequest = {
  dataset_id: string
  question: string
  retrieval_mode: RetrievalMode
  filters: QueryFilters
  include_trace: boolean
  top_k?: number
}

/* ─── Fetch client ──────────────────────────────────────────────────── */

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? 'http://localhost:8000' : '')

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

type ApiOptions = {
  token: string
  method?: Method
  body?: unknown
  searchParams?: Record<string, string | number | undefined | null>
}

function buildQuery(params?: ApiOptions['searchParams']): string {
  if (!params) return ''
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== '',
  )
  if (entries.length === 0) return ''
  const qs = new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))
  return `?${qs.toString()}`
}

async function apiFetch(path: string, options: ApiOptions): Promise<unknown> {
  const url = `${API_BASE_URL}${path}${buildQuery(options.searchParams)}`
  const headers: Record<string, string> = {
    Authorization: `Bearer ${options.token}`,
    'Content-Type': 'application/json',
  }
  const response = await fetch(url, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const text = await response.text()
      if (text) message = text
    } catch {
      /* ignore */
    }
    throw new Error(message)
  }
  if (response.status === 204) return null
  return response.json()
}

async function apiFormFetch(
  path: string,
  token: string,
  body: FormData,
): Promise<unknown> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body,
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const text = await response.text()
      if (text) message = text
    } catch {
      /* ignore */
    }
    throw new Error(message)
  }
  return response.json()
}

/* ─── Pagination ────────────────────────────────────────────────────── */

export const pageSchema = <T extends z.ZodTypeAny>(itemSchema: T) =>
  z.object({
    items: z.array(itemSchema),
    total: z.number(),
    limit: z.number(),
    offset: z.number(),
  })

export type Page<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type PageParams = { limit?: number; offset?: number }

const registerCorpusResponseSchema = z.object({
  dataset: datasetSchema,
  documents: z.array(documentSchema),
  created_count: z.number(),
  reused_count: z.number(),
  job_ids: z.array(z.string()),
  queued_document_ids: z.array(z.string()),
  skipped_document_ids: z.array(z.string()),
})

const uploadDocumentsResponseSchema = z.object({
  documents: z.array(documentSchema),
  job_ids: z.array(z.string()),
  queued_document_ids: z.array(z.string()),
  skipped_document_ids: z.array(z.string()),
})

const ingestResponseSchema = z.object({
  job_ids: z.array(z.string()),
  queued_document_ids: z.array(z.string()),
  skipped_document_ids: z.array(z.string()),
})

const evaluationCreateResponseSchema = z.object({
  eval_run_id: z.string(),
  job_id: z.string(),
})

export const api = {
  async ready() {
    const response = await fetch(`${API_BASE_URL}/ready`)
    return readySchema.parse(await response.json())
  },
  async readyAuthed(token: string) {
    return readySchema.parse(await apiFetch('/ready', { token }))
  },
  /* datasets */
  async datasets(token: string, params: PageParams = {}) {
    return pageSchema(datasetSchema).parse(
      await apiFetch('/v1/datasets', {
        token,
        searchParams: {
          limit: params.limit ?? 50,
          offset: params.offset ?? 0,
        },
      }),
    )
  },
  async dataset(token: string, id: string) {
    return datasetSchema.parse(await apiFetch(`/v1/datasets/${id}`, { token }))
  },
  async createDataset(
    token: string,
    body: { name: string; description?: string },
  ) {
    return datasetSchema.parse(
      await apiFetch('/v1/datasets', { token, method: 'POST', body }),
    )
  },
  async patchDataset(
    token: string,
    id: string,
    body: {
      name?: string
      description?: string
      default_query_settings?: Record<string, unknown>
    },
  ) {
    return datasetSchema.parse(
      await apiFetch(`/v1/datasets/${id}`, { token, method: 'PATCH', body }),
    )
  },
  async registerLocalCorpus(
    token: string,
    body: { dataset_name: string; description?: string; path?: string },
  ) {
    return registerCorpusResponseSchema.parse(
      await apiFetch('/v1/datasets/register-local-corpus', {
        token,
        method: 'POST',
        body,
      }),
    )
  },
  /* documents */
  async documents(
    token: string,
    datasetId: string,
    params: PageParams & {
      ticker?: string
      form_type?: string
      ingestion_status?: string
      q?: string
    } = {},
  ) {
    return pageSchema(documentSchema).parse(
      await apiFetch(`/v1/datasets/${datasetId}/documents`, {
        token,
        searchParams: {
          ticker: params.ticker,
          form_type: params.form_type,
          ingestion_status: params.ingestion_status,
          q: params.q,
          limit: params.limit ?? 50,
          offset: params.offset ?? 0,
        },
      }),
    )
  },
  async uploadDocuments(
    token: string,
    datasetId: string,
    files: FileList | Array<File>,
  ) {
    const formData = new FormData()
    Array.from(files).forEach((file) => formData.append('files', file))
    return uploadDocumentsResponseSchema.parse(
      await apiFormFetch(
        `/v1/datasets/${datasetId}/documents`,
        token,
        formData,
      ),
    )
  },
  async patchDocument(
    token: string,
    documentId: string,
    body: {
      ticker?: string
      company_name?: string | null
      form_type?: string
      filing_date?: string | null
      report_period?: string | null
      fiscal_year?: number | null
      fiscal_quarter?: number | null
    },
  ) {
    return documentSchema.parse(
      await apiFetch(`/v1/documents/${documentId}`, {
        token,
        method: 'PATCH',
        body,
      }),
    )
  },
  async deleteDocument(token: string, documentId: string) {
    await apiFetch(`/v1/documents/${documentId}`, { token, method: 'DELETE' })
  },
  documentFileUrl(documentId: string) {
    return `${API_BASE_URL}/v1/documents/${documentId}/file`
  },
  async documentFileBlob(token: string, documentId: string) {
    const response = await fetch(this.documentFileUrl(documentId), {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`
      try {
        const text = await response.text()
        if (text) message = text
      } catch {
        /* ignore */
      }
      throw new Error(message)
    }
    return response.blob()
  },
  async documentExtracted(token: string, documentId: string) {
    return documentExtractedSchema.parse(
      await apiFetch(`/v1/documents/${documentId}/extracted`, { token }),
    )
  },
  /* ingestion */
  async ingest(
    token: string,
    datasetId: string,
    body: {
      document_ids?: Array<string>
      minio_prefix?: string
      force: boolean
    },
  ) {
    return ingestResponseSchema.parse(
      await apiFetch(`/v1/datasets/${datasetId}/ingestions`, {
        token,
        method: 'POST',
        body,
      }),
    )
  },
  async ingestionRuns(token: string, datasetId: string) {
    return z
      .array(ingestionRunSchema)
      .parse(
        await apiFetch(`/v1/datasets/${datasetId}/ingestion-runs`, { token }),
      )
  },
  /* jobs */
  async jobs(
    token: string,
    params: PageParams & {
      dataset_id?: string
      job_type?: string
      status?: string
    } = {},
  ) {
    return pageSchema(jobSchema).parse(
      await apiFetch('/v1/jobs', {
        token,
        searchParams: {
          dataset_id: params.dataset_id,
          job_type: params.job_type,
          status: params.status,
          limit: params.limit ?? 50,
          offset: params.offset ?? 0,
        },
      }),
    )
  },
  async job(token: string, id: string) {
    return jobSchema.parse(await apiFetch(`/v1/jobs/${id}`, { token }))
  },
  async cancelJob(token: string, id: string) {
    return jobSchema.parse(
      await apiFetch(`/v1/jobs/${id}/cancel`, { token, method: 'POST' }),
    )
  },
  async retryJob(token: string, id: string) {
    return jobSchema.parse(
      await apiFetch(`/v1/jobs/${id}/retry`, { token, method: 'POST' }),
    )
  },
  async sweepJobs(token: string) {
    return jobSweepResponseSchema.parse(
      await apiFetch('/v1/jobs/sweep', { token, method: 'POST' }),
    )
  },
  /* query */
  async query(token: string, body: QueryRequest) {
    return queryResponseSchema.parse(
      await apiFetch('/v1/query', { token, method: 'POST', body }),
    )
  },
  /* traces */
  async trace(token: string, traceId: string) {
    return traceSchema.parse(await apiFetch(`/v1/traces/${traceId}`, { token }))
  },
  async traces(
    token: string,
    params?: { dataset_id?: string; question?: string; limit?: number },
  ) {
    return z.array(traceSummarySchema).parse(
      await apiFetch('/v1/traces', {
        token,
        searchParams: {
          dataset_id: params?.dataset_id,
          question_contains: params?.question,
          limit: params?.limit ?? 50,
        },
      }),
    )
  },
  /* evaluations */
  async evaluations(
    token: string,
    params: PageParams & { dataset_id?: string } = {},
  ) {
    return pageSchema(evalRunSchema).parse(
      await apiFetch('/v1/evaluations', {
        token,
        searchParams: {
          dataset_id: params.dataset_id,
          limit: params.limit ?? 50,
          offset: params.offset ?? 0,
        },
      }),
    )
  },
  async evaluation(token: string, id: string) {
    return evalRunSchema.parse(
      await apiFetch(`/v1/evaluations/${id}`, { token }),
    )
  },
  async createEvaluation(
    token: string,
    body: {
      dataset_id: string
      cases?: Array<{
        question: string
        expected_answer?: string
        expected_answer_spec?: Record<string, unknown>
        expected_evidence?: Array<Record<string, unknown>>
        verification_status?: string
        tags?: Array<string>
      }>
      case_ids?: Array<string>
      system_variants?: Array<RetrievalMode>
      benchmark_profile?: 'scientific' | 'diagnostic'
    },
  ) {
    return evaluationCreateResponseSchema.parse(
      await apiFetch('/v1/evaluations', { token, method: 'POST', body }),
    )
  },
  /* eval cases */
  async evalCases(
    token: string,
    params: PageParams & {
      dataset_id?: string
      category?: string
      difficulty?: string
      tag?: string
    } = {},
  ) {
    return pageSchema(evalCaseSchema).parse(
      await apiFetch('/v1/eval-cases', {
        token,
        searchParams: {
          dataset_id: params.dataset_id,
          category: params.category,
          difficulty: params.difficulty,
          tag: params.tag,
          limit: params.limit ?? 50,
          offset: params.offset ?? 0,
        },
      }),
    )
  },
  async evalCase(token: string, id: string) {
    return evalCaseSchema.parse(
      await apiFetch(`/v1/eval-cases/${id}`, { token }),
    )
  },
  async createEvalCase(
    token: string,
    body: {
      dataset_id: string
      case_key?: string
      category?: string
      difficulty?: string
      question: string
      expected_answer?: string | null
      expected_citations?: Array<Record<string, unknown>>
      expected_answer_spec?: Record<string, unknown>
      expected_evidence?: Array<Record<string, unknown>>
      verification_status?: string
      verified_by?: string | null
      verified_at?: string | null
      gold_version?: string
      tags?: Array<string>
    },
  ) {
    return evalCaseSchema.parse(
      await apiFetch('/v1/eval-cases', { token, method: 'POST', body }),
    )
  },
  async patchEvalCase(
    token: string,
    id: string,
    body: {
      case_key?: string | null
      category?: string | null
      difficulty?: string | null
      question?: string
      expected_answer?: string | null
      expected_citations?: Array<Record<string, unknown>>
      expected_answer_spec?: Record<string, unknown> | null
      expected_evidence?: Array<Record<string, unknown>> | null
      verification_status?: string | null
      verified_by?: string | null
      verified_at?: string | null
      gold_version?: string | null
      tags?: Array<string>
    },
  ) {
    return evalCaseSchema.parse(
      await apiFetch(`/v1/eval-cases/${id}`, {
        token,
        method: 'PATCH',
        body,
      }),
    )
  },
  async deleteEvalCase(token: string, id: string) {
    await apiFetch(`/v1/eval-cases/${id}`, { token, method: 'DELETE' })
  },
}
