import { describe, expect, it } from 'vitest'

import {
  citationSchema,
  datasetSchema,
  documentSchema,
  evalCaseSchema,
  evalResultSchema,
  evalRunSchema,
  jobSchema,
  queryResponseSchema,
  traceSchema,
} from './api'

describe('datasetSchema', () => {
  it('accepts a well-formed dataset payload', () => {
    const result = datasetSchema.safeParse({
      id: 'd1',
      name: 'sec-filings',
      description: null,
      default_query_settings: {},
      created_at: '2026-01-01T00:00:00Z',
      document_count: 0,
      active_chunk_count: 0,
      completed_ingestion_count: 0,
    })
    expect(result.success).toBe(true)
  })

  it('rejects missing required fields', () => {
    const result = datasetSchema.safeParse({ id: 'd1' })
    expect(result.success).toBe(false)
  })
})

describe('documentSchema', () => {
  it('parses with nullable filing fields', () => {
    const result = documentSchema.safeParse({
      id: 'doc1',
      dataset_id: 'd1',
      ticker: 'AAPL',
      company_name: null,
      form_type: '10-K',
      filing_date: null,
      report_period: null,
      fiscal_year: null,
      fiscal_quarter: null,
      checksum: 'abc',
      minio_bucket: 'b',
      minio_key: 'k',
      minio_version_id: null,
      byte_size: 0,
      active_ingestion_run_id: null,
      ingestion_status: null,
      created_at: '2026-01-01T00:00:00Z',
    })
    expect(result.success).toBe(true)
  })
})

describe('jobSchema', () => {
  it('requires retry_count', () => {
    const valid = jobSchema.safeParse({
      id: 'j1',
      job_type: 'ingestion',
      status: 'queued',
      progress: 0,
      current_step: null,
      dataset_id: null,
      document_id: null,
      eval_run_id: null,
      error: null,
      metadata: {},
      started_at: null,
      completed_at: null,
      last_heartbeat_at: null,
      retry_count: 0,
      created_at: '2026-01-01T00:00:00Z',
    })
    expect(valid.success).toBe(true)
  })
})

describe('queryResponseSchema', () => {
  it('parses a minimal response', () => {
    const result = queryResponseSchema.safeParse({
      answer: 'A',
      citations: [],
      evidence: [],
      trace_id: 't1',
      confidence: 0.9,
      insufficiency_reason: null,
    })
    expect(result.success).toBe(true)
  })

  it('parses a citation', () => {
    const citation = citationSchema.parse({
      document_id: 'd1',
      ticker: 'AAPL',
      form_type: '10-K',
      filing_date: null,
      report_period: null,
      page_number: 12,
      chunk_id: 'c1',
      minio_bucket: 'b',
      minio_key: 'k',
      minio_version_id: null,
      snippet: 'Apple revenue was $94B.',
      label: '[AAPL]',
    })
    expect(citation.snippet).toContain('94B')
  })
})

describe('evalCaseSchema', () => {
  it('accepts optional case_key, category, difficulty', () => {
    const result = evalCaseSchema.safeParse({
      id: 'ec1',
      dataset_id: 'd1',
      case_key: 'aapl_q1',
      category: 'single_company_lookup',
      difficulty: 'easy',
      question: 'What was AAPL revenue?',
      expected_answer: null,
      expected_citations: [],
      tags: ['revenue'],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.case_key).toBe('aapl_q1')
    }
  })

  it('tolerates missing optional fields', () => {
    const result = evalCaseSchema.safeParse({
      id: 'ec2',
      dataset_id: null,
      question: 'What?',
      expected_answer: null,
      expected_citations: [],
      tags: [],
      created_at: '2026-01-01T00:00:00Z',
    })
    expect(result.success).toBe(true)
  })
})

describe('evalResultSchema', () => {
  it('parses metrics with new usage/cost/latency fields', () => {
    const result = evalResultSchema.safeParse({
      id: 'r1',
      eval_case_id: 'ec1',
      retrieval_mode: 'full_agentic',
      answer: 'A',
      trace_id: 't1',
      metrics: { recall_at_5: 0.8 },
      error: null,
      usage: { generator: { total_tokens: 100 } },
      cost_estimate: { generator: 0.001 },
      latency_ms: 1500,
    })
    expect(result.success).toBe(true)
  })

  it('tolerates missing new fields for backward compat', () => {
    const result = evalResultSchema.safeParse({
      id: 'r1',
      eval_case_id: null,
      retrieval_mode: 'llm_only',
      answer: null,
      trace_id: null,
      metrics: {},
      error: null,
    })
    expect(result.success).toBe(true)
  })
})

describe('evalRunSchema', () => {
  it('parses a run with aggregate metrics', () => {
    const result = evalRunSchema.safeParse({
      id: 'run1',
      dataset_id: 'd1',
      job_id: 'j1',
      status: 'completed',
      run_config: {},
      system_variant: 'full_agentic',
      model_metadata: {},
      metrics: {
        full_agentic: {
          avg_recall_at_5: 0.7,
          citation_validity_rate: 0.85,
          total_cost_usd: 0.05,
        },
      },
      errors: [],
      results: [],
      created_at: '2026-01-01T00:00:00Z',
    })
    expect(result.success).toBe(true)
  })
})

describe('traceSchema', () => {
  it('parses a trace with empty arrays', () => {
    const result = traceSchema.safeParse({
      id: 't1',
      dataset_id: 'd1',
      user_question: 'q',
      retrieval_mode: 'full_agentic',
      plan: {},
      retrieval_calls: [],
      verifier_result: {},
      model_metadata: {},
      final_answer_metadata: {},
      timings: {},
      citations: [],
      created_at: '2026-01-01T00:00:00Z',
    })
    expect(result.success).toBe(true)
  })
})
