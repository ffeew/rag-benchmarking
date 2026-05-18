import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Copy, KeyRound, LogOut } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { Skeleton } from '#/components/ui/skeleton'
import { StatusDot } from '#/components/ui/status-dot'
import { KeyValueGrid } from '#/components/data/KeyValueGrid'
import type { KVRow } from '#/components/data/KeyValueGrid'
import { api } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { toast } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/system')({ component: SystemPage })

function SystemPage() {
  const { token, isAuthed, clearToken } = useToken()
  const navigate = useNavigate()
  const ready = useQuery({
    queryKey: qk.ready,
    queryFn: api.ready,
    refetchInterval: 5000,
    enabled: isAuthed,
  })

  const [revealed, setRevealed] = useState(false)
  const tokenDisplay = revealed ? token : token.replace(/./g, (_, i) => (i < 4 || i >= token.length - 4 ? token[i] : '•'))

  const providers = ready.data?.providers ?? {}
  const mode = providers.allow_mock_providers === true ? 'mock' : 'live'

  const providerRows: Array<KVRow> = []
  for (const k of [
    'zai_chat_model',
    'zai_judge_model',
    'openrouter_embedding_model',
    'openrouter_rerank_model',
    'mistral_ocr_model',
  ]) {
    if (providers[k] !== undefined && providers[k] !== null) {
      providerRows.push({
        key: k.replace(/^(openrouter|zai)_/, '').replace(/_/g, ' '),
        value: String(providers[k]),
        mono: true,
        copyable: true,
      })
    }
  }

  const retrievalRows: Array<KVRow> = []
  for (const k of [
    'semantic_candidates',
    'full_text_candidates',
    'fused_candidates',
    'evidence_top_k',
    'rerank_candidates',
    'reranker_enabled',
  ]) {
    if (providers[k] !== undefined && providers[k] !== null) {
      retrievalRows.push({
        key: k.replace(/_/g, ' '),
        value: String(providers[k]),
        mono: true,
      })
    }
  }

  const chunkingRows: Array<KVRow> = []
  for (const k of [
    'chunk_target_tokens',
    'chunk_max_tokens',
    'chunk_overlap_tokens',
    'table_max_rows',
    'embedding_dimension',
  ]) {
    if (providers[k] !== undefined && providers[k] !== null) {
      chunkingRows.push({
        key: k.replace(/_/g, ' '),
        value: String(providers[k]),
        mono: true,
      })
    }
  }

  function copyToken() {
    try {
      void navigator.clipboard.writeText(token)
      toast.success('Token copied')
    } catch {
      toast.error('Copy failed')
    }
  }

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-5 px-6 py-6">
      <header>
        <div className="mono-label text-[var(--ink-muted)]">SYSTEM</div>
        <h1 className="mt-1 text-[24px] leading-tight font-semibold tracking-tight">
          Health, configuration & session
        </h1>
      </header>

      {/* Health */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <HealthCard label="API" status={ready.data?.status} loading={ready.isLoading} />
        <HealthCard label="DATABASE" status={ready.data?.database ? 'ready' : 'failed'} loading={ready.isLoading} />
        <HealthCard label="MINIO" status={ready.data?.minio ? 'ready' : 'failed'} loading={ready.isLoading} />
        <HealthCard label="REDIS" status={ready.data?.redis ? 'ready' : 'failed'} loading={ready.isLoading} />
      </section>

      <section className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="PROVIDERS"
            actions={
              <Badge tone={mode === 'mock' ? 'warn' : 'ok'} size="sm">
                {mode}
              </Badge>
            }
          />
          <CardBody>
            {ready.isLoading ? (
              <div className="grid gap-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-5" />
                ))}
              </div>
            ) : providerRows.length === 0 ? (
              <p className="text-[12.5px] text-[var(--ink-muted)]">No provider configuration exposed.</p>
            ) : (
              <KeyValueGrid rows={providerRows} />
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="SESSION" />
          <CardBody className="grid gap-3">
            <div>
              <div className="mono-label mb-1">CURRENT TOKEN</div>
              <div className="flex items-center gap-2">
                <code className="flex-1 truncate rounded-[3px] border border-[var(--rule)] bg-[var(--surface-2)] px-2 py-1.5 font-mono text-[11px] text-[var(--ink)]">
                  {tokenDisplay || '— none —'}
                </code>
                <Button variant="secondary" size="sm" onClick={() => setRevealed((v) => !v)}>
                  {revealed ? 'Hide' : 'Reveal'}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={copyToken}
                  leading={<Copy className="h-3 w-3" />}
                >
                  Copy
                </Button>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                leading={<KeyRound className="h-3.5 w-3.5" />}
                onClick={() => void navigate({ ...paths.auth })}
              >
                Replace token
              </Button>
              <Button
                variant="ghost"
                size="sm"
                leading={<LogOut className="h-3.5 w-3.5" />}
                onClick={() => {
                  clearToken()
                  toast.info('Signed out')
                  void navigate({ ...paths.auth })
                }}
              >
                Sign out
              </Button>
            </div>
          </CardBody>
        </Card>

        <Card className="lg:col-span-1">
          <CardHeader title="RETRIEVAL DEFAULTS" />
          <CardBody>
            {retrievalRows.length === 0 ? (
              <p className="text-[12.5px] text-[var(--ink-muted)]">No retrieval settings exposed.</p>
            ) : (
              <KeyValueGrid rows={retrievalRows} />
            )}
          </CardBody>
        </Card>

        <Card className="lg:col-span-1">
          <CardHeader title="CHUNKING & EMBEDDING" />
          <CardBody>
            {chunkingRows.length === 0 ? (
              <p className="text-[12.5px] text-[var(--ink-muted)]">No chunking settings exposed.</p>
            ) : (
              <KeyValueGrid rows={chunkingRows} />
            )}
          </CardBody>
        </Card>
      </section>
    </div>
  )
}

function HealthCard({
  label,
  status,
  loading,
}: {
  label: string
  status?: string | null
  loading?: boolean
}) {
  if (loading) {
    return (
      <div className="border border-[var(--rule)] bg-[var(--surface)] rounded-[4px] p-3.5">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="mt-2 h-4 w-12" />
      </div>
    )
  }
  const ok = status === 'ready'
  return (
    <div className="border border-[var(--rule)] bg-[var(--surface)] rounded-[4px] p-3.5 flex items-center justify-between">
      <div>
        <div className="mono-label">{label}</div>
        <div className={`font-mono text-[13px] mt-0.5 ${ok ? 'text-[var(--ok)]' : 'text-[var(--bad)]'}`}>
          {status ?? '–'}
        </div>
      </div>
      <StatusDot status={ok ? 'ready' : 'failed'} size={10} pulse={!ok} />
    </div>
  )
}
