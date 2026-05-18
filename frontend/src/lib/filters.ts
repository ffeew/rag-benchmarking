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
