import { describe, expect, it } from 'vitest'

import {
  formatBytes,
  formatDuration,
  formatNumber,
  formatPercent,
  formatScore,
  truncate,
  truncateId,
} from './format'

describe('formatBytes', () => {
  it('returns 0 B for falsy or sub-1 inputs', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(0.4)).toBe('0 B')
  })

  it('formats bytes, KB, MB, and GB units', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2_500)).toBe('2.5 KB')
    expect(formatBytes(5_500_000)).toBe('5.5 MB')
    expect(formatBytes(2_500_000_000)).toBe('2.5 GB')
  })
})

describe('formatDuration', () => {
  it('returns dash for invalid input', () => {
    expect(formatDuration(NaN)).toBe('–')
    expect(formatDuration(-5)).toBe('–')
  })

  it('handles sub-millisecond and millisecond inputs', () => {
    expect(formatDuration(0.5)).toBe('<1 ms')
    expect(formatDuration(125)).toBe('125 ms')
  })

  it('formats seconds and minutes', () => {
    expect(formatDuration(2_500)).toBe('2.50 s')
    expect(formatDuration(75_000)).toMatch(/^1m \d{2}s$/)
  })
})

describe('formatPercent', () => {
  it('renders a percentage with optional digits', () => {
    expect(formatPercent(0.123)).toBe('12%')
    expect(formatPercent(0.123, 1)).toBe('12.3%')
  })

  it('returns dash for non-finite values', () => {
    expect(formatPercent(NaN)).toBe('–')
    expect(formatPercent(Infinity)).toBe('–')
  })
})

describe('formatNumber', () => {
  it('uses en locale grouping by default', () => {
    expect(formatNumber(1_000_000)).toBe('1,000,000')
  })

  it('returns dash for non-finite values', () => {
    expect(formatNumber(NaN)).toBe('–')
  })
})

describe('formatScore', () => {
  it('uses 3-digit precision by default', () => {
    expect(formatScore(0.12345)).toBe('0.123')
  })

  it('accepts a custom digits arg', () => {
    expect(formatScore(0.5, 1)).toBe('0.5')
  })
})

describe('truncateId', () => {
  it('passes through short ids', () => {
    expect(truncateId('short')).toBe('short')
  })

  it('truncates long ids with the configured head/tail', () => {
    const out = truncateId('a'.repeat(40), 4, 4)
    expect(out.length).toBeLessThan(40)
    expect(out.startsWith('aaaa')).toBe(true)
    expect(out.endsWith('aaaa')).toBe(true)
  })
})

describe('truncate', () => {
  it('preserves strings shorter than max', () => {
    expect(truncate('hello', 10)).toBe('hello')
  })

  it('truncates and appends ellipsis', () => {
    const out = truncate('hello world hello', 6)
    expect(out.length).toBe(6)
    expect(out.endsWith('…')).toBe(true)
  })
})
