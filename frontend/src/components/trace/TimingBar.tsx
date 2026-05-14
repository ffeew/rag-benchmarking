import { Tooltip } from '#/components/ui/tooltip'
import { formatDuration } from '#/lib/format'

const STAGE_COLORS: Record<string, string> = {
  plan: 'var(--accent)',
  planning: 'var(--accent)',
  retrieve: 'var(--cite)',
  retrieval: 'var(--cite)',
  rerank: 'var(--warn)',
  reranking: 'var(--warn)',
  verify: 'var(--ok)',
  verification: 'var(--ok)',
  generate: '#a855f7',
  generation: '#a855f7',
  retry: 'var(--bad)',
}

function colorFor(stage: string): string {
  const key = stage.toLowerCase()
  return STAGE_COLORS[key] ?? 'var(--ink-muted)'
}

export function TimingBar({
  timings,
}: {
  timings: Record<string, unknown>
}) {
  const stages = Object.entries(timings)
    .map(([name, value]) => ({
      name,
      ms: typeof value === 'number' ? value : 0,
    }))
    .filter((s) => s.ms > 0)
    .sort((a, b) => orderRank(a.name) - orderRank(b.name))

  if (stages.length === 0) {
    return (
      <div className="rounded-[3px] border border-dashed border-[var(--rule)] px-3 py-2 font-mono text-[11px] text-[var(--ink-muted)]">
        No timing data recorded.
      </div>
    )
  }

  const total = stages.reduce((s, x) => s + x.ms, 0)

  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between">
        <span className="mono-label">EXECUTION</span>
        <span className="font-mono numeric text-[12px] text-[var(--ink)]">
          {formatDuration(total)} total
        </span>
      </div>
      <div className="flex h-6 w-full overflow-hidden rounded-[3px] border border-[var(--rule)]">
        {stages.map((stage) => {
          const pct = (stage.ms / total) * 100
          return (
            <Tooltip
              key={stage.name}
              content={
                <div className="grid gap-0.5 font-mono text-[11px]">
                  <span className="text-[var(--ink)]">{stage.name}</span>
                  <span className="text-[var(--ink-dim)]">
                    {formatDuration(stage.ms)} · {pct.toFixed(1)}%
                  </span>
                </div>
              }
            >
              <div
                className="relative flex items-center justify-center transition-opacity hover:opacity-80"
                style={{ width: `${pct}%`, backgroundColor: colorFor(stage.name) }}
              >
                {pct > 14 && (
                  <span className="px-1.5 font-mono text-[10.5px] uppercase tracking-wide text-white drop-shadow-sm truncate">
                    {stage.name}
                  </span>
                )}
              </div>
            </Tooltip>
          )
        })}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3 lg:grid-cols-5">
        {stages.map((stage) => (
          <div
            key={`legend-${stage.name}`}
            className="flex items-center gap-1.5 font-mono text-[11px]"
          >
            <span
              className="inline-block h-2.5 w-2.5 rounded-[1px]"
              style={{ backgroundColor: colorFor(stage.name) }}
            />
            <span className="text-[var(--ink-dim)] uppercase tracking-wide truncate">
              {stage.name}
            </span>
            <span className="ml-auto numeric text-[var(--ink-muted)]">
              {formatDuration(stage.ms)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function orderRank(name: string): number {
  const order = ['plan', 'planning', 'retrieve', 'retrieval', 'rerank', 'verify', 'verification', 'generate', 'generation']
  const lc = name.toLowerCase()
  const idx = order.findIndex((o) => lc.includes(o))
  return idx === -1 ? 99 : idx
}
