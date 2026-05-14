import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Key, LogOut, ShieldCheck, ShieldX } from 'lucide-react'

import { StatusDot } from '#/components/ui/status-dot'
import {
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownMenu,
  DropdownSeparator,
  DropdownTrigger,
} from '#/components/ui/dropdown'
import { api } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import { useToken } from '#/providers/TokenProvider'
import { toast } from '#/providers/ToastProvider'

export function TokenMenu() {
  const { token, clearToken } = useToken()
  const navigate = useNavigate()
  const ready = useQuery({
    queryKey: qk.ready,
    queryFn: api.ready,
    refetchInterval: 12_000,
    refetchOnWindowFocus: true,
  })

  const status = ready.data?.status ?? 'checking'
  const isReady = status === 'ready'

  return (
    <DropdownMenu>
      <DropdownTrigger asChild>
        <button
          type="button"
          className="inline-flex h-7 items-center gap-2 rounded-[3px] border border-[var(--rule)] bg-[var(--surface)] pl-2 pr-2.5 hover:bg-[var(--surface-2)] transition-colors"
        >
          <StatusDot status={status} size={7} pulse={!isReady} />
          <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-[var(--ink-dim)]">
            {status}
          </span>
        </button>
      </DropdownTrigger>
      <DropdownContent className="min-w-[260px]">
        <DropdownLabel>SYSTEM</DropdownLabel>
        <div className="px-3 pb-1.5 grid gap-1 font-mono text-[11px]">
          <Row label="api" ok={status === 'ready'} />
          <Row label="database" ok={Boolean(ready.data?.database)} />
          <Row label="minio" ok={Boolean(ready.data?.minio)} />
          <Row label="redis" ok={Boolean(ready.data?.redis)} />
        </div>
        <DropdownSeparator />
        <DropdownLabel>SESSION</DropdownLabel>
        <div className="px-3 pb-1.5 font-mono text-[11px] text-[var(--ink-muted)]">
          token{' '}
          <span className="text-[var(--ink-dim)]">
            {token ? `${token.slice(0, 4)}…${token.slice(-4)}` : 'none'}
          </span>
        </div>
        <DropdownSeparator />
        <DropdownItem onSelect={() => navigate({ to: '/system' })}>
          <Key className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
          Manage token
        </DropdownItem>
        <DropdownItem
          onSelect={() => {
            clearToken()
            toast.info('Signed out')
            void navigate({ to: '/auth' })
          }}
        >
          <LogOut className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
          Sign out
        </DropdownItem>
      </DropdownContent>
    </DropdownMenu>
  )
}

function Row({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[var(--ink-muted)]">{label}</span>
      <span className="inline-flex items-center gap-1">
        {ok ? (
          <>
            <ShieldCheck className="h-3 w-3 text-[var(--ok)]" />
            <span className="text-[var(--ok)]">ready</span>
          </>
        ) : (
          <>
            <ShieldX className="h-3 w-3 text-[var(--bad)]" />
            <span className="text-[var(--bad)]">down</span>
          </>
        )}
      </span>
    </div>
  )
}
