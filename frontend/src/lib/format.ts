import { formatDistanceToNowStrict, format as formatFn } from 'date-fns'

export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 1) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(units.length - 1, Math.floor(Math.log10(bytes) / 3))
  const value = bytes / Math.pow(1000, i)
  const precision = value < 10 && i > 0 ? 1 : 0
  return `${value.toFixed(precision)} ${units[i]}`
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '–'
  if (ms < 1) return '<1 ms'
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`
  const seconds = Math.round(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return `${minutes}m ${remainder.toString().padStart(2, '0')}s`
}

export function formatPercent(value: number, digits = 0): string {
  if (!Number.isFinite(value)) return '–'
  return `${(value * 100).toFixed(digits)}%`
}

export function formatNumber(value: number, opts?: Intl.NumberFormatOptions): string {
  if (!Number.isFinite(value)) return '–'
  return new Intl.NumberFormat('en', opts).format(value)
}

export function formatDate(value?: string | Date | null): string {
  if (!value) return '–'
  const d = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(d.getTime())) return '–'
  return formatFn(d, 'MMM d, yyyy')
}

export function formatDateTime(value?: string | Date | null): string {
  if (!value) return '–'
  const d = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(d.getTime())) return '–'
  return formatFn(d, 'MMM d, yyyy · HH:mm:ss')
}

export function formatRelative(value?: string | Date | null): string {
  if (!value) return '–'
  const d = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(d.getTime())) return '–'
  return formatDistanceToNowStrict(d, { addSuffix: true })
}

export function truncateId(id: string, head = 8, tail = 4): string {
  if (id.length <= head + tail + 1) return id
  return `${id.slice(0, head)}…${id.slice(-tail)}`
}

export function truncate(text: string, max: number): string {
  if (text.length <= max) return text
  return `${text.slice(0, max - 1).trimEnd()}…`
}

export function formatScore(score: number, digits = 3): string {
  if (!Number.isFinite(score)) return '–'
  return score.toFixed(digits)
}
