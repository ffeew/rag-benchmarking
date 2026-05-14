import { Brain } from 'lucide-react'

import { Badge } from '#/components/ui/badge'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Chip } from '#/components/data/Chip'

export function PlanCard({ plan }: { plan: Record<string, unknown> }) {
  const tickers = toArray(plan['target_tickers'] ?? plan['tickers'])
  const forms = toArray(plan['forms'] ?? plan['form_types'])
  const metrics = toArray(plan['metrics'] ?? plan['topics'])
  const timeWindow = String(
    plan['time_constraint'] ?? plan['time_window'] ?? plan['time'] ?? '',
  )
  const queryType = String(plan['query_type'] ?? plan['type'] ?? '')
  const ambiguity = plan['ambiguity'] ?? plan['ambiguous']
  const planning = plan['rewritten_query'] ?? plan['planned_query']
  const ambiguityText: string | null =
    ambiguity == null ? null : typeof ambiguity === 'boolean' ? (ambiguity ? 'flagged' : 'clear') : String(ambiguity)

  return (
    <Card>
      <CardHeader
        title={
          <span className="inline-flex items-center gap-1.5">
            <Brain className="h-3.5 w-3.5 text-[var(--accent)]" />
            QUERY PLAN
          </span>
        }
      />
      <CardBody className="grid gap-3">
        {queryType && (
          <Row label="TYPE">
            <Badge tone="accent" size="sm">
              {queryType}
            </Badge>
          </Row>
        )}
        {tickers.length > 0 && (
          <Row label="TICKERS">
            <div className="flex flex-wrap gap-1">
              {tickers.map((t) => (
                <Chip key={t} tone="accent" size="sm">
                  {t}
                </Chip>
              ))}
            </div>
          </Row>
        )}
        {forms.length > 0 && (
          <Row label="FORMS">
            <div className="flex flex-wrap gap-1">
              {forms.map((f) => (
                <Chip key={f} tone="cite" size="sm">
                  {f}
                </Chip>
              ))}
            </div>
          </Row>
        )}
        {metrics.length > 0 && (
          <Row label="METRICS">
            <div className="flex flex-wrap gap-1">
              {metrics.map((m) => (
                <Chip key={m} size="sm">
                  {m}
                </Chip>
              ))}
            </div>
          </Row>
        )}
        {timeWindow && (
          <Row label="TIME">
            <span className="font-mono text-[11.5px] text-[var(--ink)]">{timeWindow}</span>
          </Row>
        )}
        {ambiguityText && (
          <Row label="AMBIGUITY">
            <Badge tone={ambiguityText === 'clear' ? 'neutral' : 'warn'} size="sm">
              {ambiguityText}
            </Badge>
          </Row>
        )}
        {planning != null && planning !== '' ? (
          <Row label="REWRITTEN">
            <span className="font-mono text-[11.5px] text-[var(--ink-dim)]">
              {String(planning)}
            </span>
          </Row>
        ) : null}
      </CardBody>
    </Card>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[80px_1fr] items-start gap-3">
      <span className="mono-label pt-0.5">{label}</span>
      <div>{children}</div>
    </div>
  )
}

function toArray(value: unknown): Array<string> {
  if (Array.isArray(value)) return value.map(String)
  if (typeof value === 'string' && value.length > 0) return [value]
  return []
}
