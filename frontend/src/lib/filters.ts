export function splitCsv(value?: string | null): Array<string> | undefined {
  if (!value) return undefined
  const items = value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  return items.length > 0 ? items : undefined
}

export function joinCsv(items?: Array<string> | null): string {
  return (items ?? []).join(', ')
}

export function uniq<T>(items: Array<T>): Array<T> {
  return Array.from(new Set(items))
}

export function toggleInArray<T>(items: Array<T>, item: T): Array<T> {
  return items.includes(item) ? items.filter((i) => i !== item) : [...items, item]
}
