import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { CitationCard } from './CitationCard'
import type { Citation } from '#/lib/api'

function makeCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    document_id: 'doc-1',
    ticker: 'AAPL',
    form_type: '10-K',
    filing_date: '2025-10-31',
    report_period: null,
    page_number: 32,
    chunk_id: 'chunk-1',
    minio_bucket: 'bucket',
    minio_key: 'raw/AAPL/10-K/2025-10-31/abc.pdf',
    minio_version_id: null,
    snippet: 'Apple total net sales were $94 billion in fiscal 2025.',
    label: '[AAPL 2025-10-31 10-K, p. 32]',
    ...overrides,
  }
}

describe('CitationCard', () => {
  it('renders ticker, form, page, and snippet', () => {
    render(<CitationCard citation={makeCitation()} index={1} />)
    expect(screen.getByText('AAPL')).toBeTruthy()
    expect(screen.getByText('10-K')).toBeTruthy()
    expect(screen.getByText(/p\. 32/)).toBeTruthy()
    expect(screen.getByText(/Apple total net sales/)).toBeTruthy()
  })

  it('invokes onSelect with the index when clicked', () => {
    const onSelect = vi.fn()
    render(<CitationCard citation={makeCitation()} index={3} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button'))
    expect(onSelect).toHaveBeenCalledWith(3)
  })

  it('truncates a long minio_key visually but renders it', () => {
    const citation = makeCitation({
      minio_key: 'raw/' + 'x'.repeat(120),
    })
    render(<CitationCard citation={citation} index={1} />)
    expect(screen.getByText(/x{20}/)).toBeTruthy()
  })

  it('shows a fallback dash when filing_date is null', () => {
    const citation = makeCitation({ filing_date: null })
    render(<CitationCard citation={citation} index={1} />)
    // formatDate returns '–' for null
    expect(screen.getByText('–')).toBeTruthy()
  })
})
