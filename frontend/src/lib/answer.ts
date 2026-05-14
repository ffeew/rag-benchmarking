export type AnswerSegment =
  | { kind: 'text'; text: string }
  | { kind: 'citation'; label: string; index: number }

const CITATION_RE = /\[(\d+(?:[\s,]+\d+)*)\]/g

export function parseAnswerCitations(answer: string): Array<AnswerSegment> {
  const out: Array<AnswerSegment> = []
  let cursor = 0
  for (const match of answer.matchAll(CITATION_RE)) {
    const start = match.index
    if (start > cursor) {
      out.push({ kind: 'text', text: answer.slice(cursor, start) })
    }
    const indexes = match[1]
      .split(/[\s,]+/)
      .map((s) => Number.parseInt(s, 10))
      .filter((n) => Number.isFinite(n))
    for (const n of indexes) {
      out.push({ kind: 'citation', label: String(n), index: n })
    }
    cursor = start + match[0].length
  }
  if (cursor < answer.length) {
    out.push({ kind: 'text', text: answer.slice(cursor) })
  }
  return out
}
