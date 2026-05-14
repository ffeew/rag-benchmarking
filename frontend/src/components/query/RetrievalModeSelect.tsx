import { Bot, Layers, Zap } from 'lucide-react'

import { Segmented } from '#/components/ui/segmented'
import { Tooltip } from '#/components/ui/tooltip'
import type { RetrievalMode } from '#/lib/api'

export function RetrievalModeSelect({
  value,
  onChange,
}: {
  value: RetrievalMode
  onChange: (value: RetrievalMode) => void
}) {
  return (
    <Segmented<RetrievalMode>
      value={value}
      onValueChange={onChange}
      options={[
        {
          value: 'full_agentic',
          label: (
            <Tooltip
              content="Plan → hybrid retrieve → verify → optional retry → generate. Default."
              side="bottom"
            >
              <span className="inline-flex items-center gap-1.5">
                <Bot className="h-3 w-3" />
                Agentic
              </span>
            </Tooltip>
          ),
        },
        {
          value: 'single_pass',
          label: (
            <Tooltip
              content="Hybrid retrieval without verifier or retry — baseline RAG."
              side="bottom"
            >
              <span className="inline-flex items-center gap-1.5">
                <Layers className="h-3 w-3" />
                Single-pass
              </span>
            </Tooltip>
          ),
        },
        {
          value: 'llm_only',
          label: (
            <Tooltip
              content="No retrieval — ablation comparing pure LLM knowledge to RAG."
              side="bottom"
            >
              <span className="inline-flex items-center gap-1.5">
                <Zap className="h-3 w-3" />
                LLM-only
              </span>
            </Tooltip>
          ),
        },
      ]}
    />
  )
}
