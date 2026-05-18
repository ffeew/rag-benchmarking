import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CitationCard } from './CitationCard'
import { api } from '#/lib/api'
import type { Citation } from '#/lib/api'

vi.mock('#/providers/TokenProvider', () => ({
  useToken: () => ({
    token: 'test-token',
    isAuthed: true,
    setToken: vi.fn(),
    clearToken: vi.fn(),
  }),
}))

vi.mock('#/lib/api', () => ({
  api: {
    documentFilePresignedUrl: vi.fn(async () => ({
      url: 'https://minio.test/sec-filings/raw/AAPL/10-K/abc.pdf',
      expires_at: '2099-01-01T00:00:00Z',
    })),
  },
}))

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

afterEach(() => {
  vi.clearAllMocks()
})

describe('CitationCard', () => {
  it('renders ticker, form, page, and snippet', () => {
    render(<CitationCard citation={makeCitation()} index={1} />)
    expect(screen.getByText('AAPL')).toBeTruthy()
    expect(screen.getByText('10-K')).toBeTruthy()
    expect(screen.getByText(/p\. 32/)).toBeTruthy()
    expect(screen.getByText(/Apple total net sales/)).toBeTruthy()
  })

  it('invokes onSelect with the index when card is clicked', () => {
    const onSelect = vi.fn()
    render(
      <CitationCard citation={makeCitation()} index={3} onSelect={onSelect} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Citation 3/ }))
    expect(onSelect).toHaveBeenCalledWith(3)
  })

  it('invokes onSelect on Enter and Space keypress', () => {
    const onSelect = vi.fn()
    render(
      <CitationCard citation={makeCitation()} index={2} onSelect={onSelect} />,
    )
    const card = screen.getByRole('button', { name: /Citation 2/ })
    fireEvent.keyDown(card, { key: 'Enter' })
    fireEvent.keyDown(card, { key: ' ' })
    expect(onSelect).toHaveBeenCalledTimes(2)
    expect(onSelect).toHaveBeenCalledWith(2)
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

  it('opens the source PDF at the cited page when the minio_key button is clicked', async () => {
    const placeholderWindow = {
      location: { href: '' },
      close: vi.fn(),
    } as unknown as Window
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(placeholderWindow)

    render(<CitationCard citation={makeCitation()} index={1} />)
    fireEvent.click(
      screen.getByRole('button', { name: /Open source PDF at page 32/ }),
    )

    expect(openSpy).toHaveBeenCalledWith('about:blank', '_blank')
    expect(api.documentFilePresignedUrl).toHaveBeenCalledWith(
      'test-token',
      'doc-1',
    )
    await waitFor(() => {
      expect(placeholderWindow.location.href).toBe(
        'https://minio.test/sec-filings/raw/AAPL/10-K/abc.pdf#page=32',
      )
    })
  })

  it('does not trigger onSelect when the PDF button is clicked', async () => {
    const placeholderWindow = {
      location: { href: '' },
      close: vi.fn(),
    } as unknown as Window
    vi.spyOn(window, 'open').mockReturnValue(placeholderWindow)
    const onSelect = vi.fn()

    render(
      <CitationCard citation={makeCitation()} index={1} onSelect={onSelect} />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: /Open source PDF at page 32/ }),
    )

    expect(onSelect).not.toHaveBeenCalled()
  })
})
