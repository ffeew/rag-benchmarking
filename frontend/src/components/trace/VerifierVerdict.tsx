import { Check, Info, Minus, X } from 'lucide-react'

import { Badge } from '#/components/ui/badge'
import { Card, CardBody, CardHeader } from '#/components/ui/card'

type ItemList = Array<string | Record<string, unknown>>

function asList(value: unknown): ItemList {
  if (Array.isArray(value)) return value
  return []
}

function asString(item: string | Record<string, unknown>): string {
  if (typeof item === 'string') return item
  return String(item.claim ?? item.text ?? JSON.stringify(item))
}

// Only the full_agentic pipeline runs the LLM verifier as a discrete step
// (see backend/packages/rag-retrieval/rag_retrieval/query.py:195-253 — the
// retrieval agent's structured output IS the verifier verdict). single_pass
// uses ``keyword_verify_evidence`` — a deterministic lexical check that
// doesn't produce per-claim verdicts. llm_only skips retrieval entirely.
// Surface that explicitly so empty SUPPORTED/MISSING sections don't read as
// "the verifier ran and found nothing."
const VERIFIER_BYPASS_BY_MODE: Record<string, string> = {
  single_pass:
    'Single-pass mode uses heuristic (keyword-overlap) verification, not the LLM verifier. No per-claim verdict is produced.',
  llm_only:
    'LLM-only mode performs no retrieval, so there is nothing to verify.',
}

export function VerifierVerdict({
  verdict,
  retrievalMode,
}: {
  verdict: Record<string, unknown>
  retrievalMode?: string
}) {
  // Backend persists ``supported_chunk_ids`` / ``missing_subclaims`` (per
  // ``rag_retrieval.verification.VerificationResult.as_dict`` and the agent path in
  // ``query.py``). The ``supported`` / ``missing`` keys are accepted as fallbacks for
  // older traces and any future verifier shape that ships those names directly.
  const supported = asList(
    verdict['supported_chunk_ids'] ?? verdict['supported'] ?? verdict['satisfied'],
  )
  const missing = asList(
    verdict['missing_subclaims'] ?? verdict['missing'] ?? verdict['unmet'],
  )
  const contradictions = asList(
    verdict['contradictions'] ?? verdict['contradictory'],
  )
  const sufficientRaw = verdict['sufficient'] ?? verdict['ok']
  const sufficient = typeof sufficientRaw === 'boolean' ? sufficientRaw : null
  const retriedRaw = verdict['retried']
  const retried = typeof retriedRaw === 'boolean' ? retriedRaw : null

  const bypassNote = retrievalMode
    ? VERIFIER_BYPASS_BY_MODE[retrievalMode]
    : undefined
  const verdictIsEmpty =
    supported.length === 0 &&
    missing.length === 0 &&
    contradictions.length === 0 &&
    sufficient === null &&
    retried === null

  return (
    <Card>
      <CardHeader
        title="VERIFIER"
        actions={
          <div className="flex items-center gap-1.5">
            {bypassNote && verdictIsEmpty && (
              <Badge tone="neutral" size="sm">
                not invoked
              </Badge>
            )}
            {retried != null && (
              <Badge tone={retried ? 'warn' : 'neutral'} size="sm">
                {retried ? 'retried' : 'no retry'}
              </Badge>
            )}
            {sufficient != null && (
              <Badge tone={sufficient ? 'ok' : 'bad'} size="sm">
                {sufficient ? 'sufficient' : 'insufficient'}
              </Badge>
            )}
          </div>
        }
      />
      <CardBody className="grid gap-3">
        {bypassNote && verdictIsEmpty ? (
          <div className="flex items-start gap-2 rounded-[2px] border-l-2 border-[var(--ink-muted)] bg-[var(--surface-2)] px-2 py-1.5 text-[11.5px] text-[var(--ink-dim)]">
            <Info className="mt-0.5 h-3 w-3 shrink-0 text-[var(--ink-muted)]" />
            <span>
              <span className="font-mono uppercase tracking-wide text-[var(--ink-muted)]">
                By design ·{' '}
              </span>
              {bypassNote}
            </span>
          </div>
        ) : (
          <>
            <Section
              title="SUPPORTED"
              tone="ok"
              icon={<Check className="h-3 w-3" />}
              items={supported.map(asString)}
            />
            <Section
              title="MISSING"
              tone="warn"
              icon={<Minus className="h-3 w-3" />}
              items={missing.map(asString)}
            />
            <Section
              title="CONTRADICTIONS"
              tone="bad"
              icon={<X className="h-3 w-3" />}
              items={contradictions.map(asString)}
            />
          </>
        )}
      </CardBody>
    </Card>
  )
}

function Section({
  title,
  tone,
  items,
  icon,
}: {
  title: string
  tone: 'ok' | 'warn' | 'bad'
  items: Array<string>
  icon: React.ReactNode
}) {
  const colorClass =
    tone === 'ok'
      ? 'text-[var(--ok)]'
      : tone === 'warn'
        ? 'text-[var(--warn)]'
        : 'text-[var(--bad)]'
  if (items.length === 0) {
    return (
      <div>
        <div
          className={`mono-label inline-flex items-center gap-1.5 ${colorClass}`}
        >
          {icon} {title}{' '}
          <span className="text-[var(--ink-muted)] font-mono numeric">0</span>
        </div>
      </div>
    )
  }
  return (
    <div>
      <div
        className={`mono-label mb-1.5 inline-flex items-center gap-1.5 ${colorClass}`}
      >
        {icon} {title}{' '}
        <span className="text-[var(--ink-muted)] font-mono numeric">
          {items.length}
        </span>
      </div>
      <ul className="grid gap-1">
        {items.map((item, i) => (
          <li
            key={i}
            className="rounded-[2px] border-l-2 bg-[var(--surface-2)] px-2 py-1 text-[11.5px] text-[var(--ink-dim)]"
            style={{
              borderColor:
                tone === 'ok'
                  ? 'var(--ok)'
                  : tone === 'warn'
                    ? 'var(--warn)'
                    : 'var(--bad)',
            }}
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}
