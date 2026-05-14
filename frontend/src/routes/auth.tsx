import { createFileRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { Eye, EyeOff, Lock, TerminalSquare } from 'lucide-react'
import { useEffect, useState } from 'react'
import { z } from 'zod'

import { Button } from '#/components/ui/button'
import { Input } from '#/components/ui/input'
import { api } from '#/lib/api'
import { useToken } from '#/providers/TokenProvider'
import { toast } from '#/providers/ToastProvider'

const searchSchema = z.object({
  return: z.string().optional(),
})

export const Route = createFileRoute('/auth')({
  component: AuthScreen,
  validateSearch: searchSchema,
})

function AuthScreen() {
  const { setToken, isAuthed } = useToken()
  const navigate = useNavigate()
  const search = useSearch({ from: '/auth' })
  const [draft, setDraft] = useState('')
  const [showToken, setShowToken] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    const value = draft.trim()
    if (!value) {
      setErr('Token is required')
      return
    }
    setSubmitting(true)
    try {
      await api.readyAuthed(value).catch(async (rawError) => {
        const message = rawError instanceof Error ? rawError.message : ''
        if (/401|unauthor|forbidden|403/i.test(message)) {
          throw new Error('Token rejected by API')
        }
        try {
          await api.ready()
        } catch {
          throw new Error('Cannot reach API — is the backend running?')
        }
      })
      setToken(value)
      toast.success('Connected')
      void navigate({ to: search.return ?? '/' })
    } catch (error) {
      setErr(error instanceof Error ? error.message : 'Failed to authenticate')
    } finally {
      setSubmitting(false)
    }
  }

  useEffect(() => {
    if (isAuthed) {
      void navigate({ to: search.return ?? '/' })
    }
  }, [isAuthed, navigate, search.return])

  return (
    <div className="relative min-h-screen w-screen overflow-hidden bg-[var(--bg)] text-[var(--ink)]">
      {/* faint grid background */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.4]"
        style={{
          backgroundImage:
            'linear-gradient(var(--rule) 1px, transparent 1px), linear-gradient(90deg, var(--rule) 1px, transparent 1px)',
          backgroundSize: '32px 32px',
          maskImage:
            'radial-gradient(ellipse at center, rgba(0,0,0,0.95), rgba(0,0,0,0.0) 70%)',
        }}
      />
      <div className="relative flex min-h-screen flex-col">
        <header className="flex h-12 items-center gap-2 border-b border-[var(--rule)] px-5">
          <TerminalSquare className="h-4 w-4 text-[var(--accent)]" />
          <span className="font-mono text-[12px] font-semibold tracking-[0.14em] text-[var(--ink)]">
            FILINGS<span className="text-[var(--ink-muted)]">/</span>DESK
          </span>
          <span className="ml-auto mono-label">v1 · operator console</span>
        </header>

        <div className="flex flex-1 items-center justify-center px-4 py-12">
          <div className="w-full max-w-md">
            <div className="mb-6">
              <div className="mono-label text-[var(--ink-muted)]">SESSION</div>
              <h1 className="mt-1 text-[26px] leading-tight font-semibold tracking-tight">
                Connect to the RAG benchmark
              </h1>
              <p className="mt-2 text-[13px] text-[var(--ink-dim)] leading-relaxed">
                Provide a Bearer token to access datasets, queries, traces, and
                evaluation runs. Stored in this session only — never persisted
                to disk.
              </p>
            </div>

            <form
              onSubmit={onSubmit}
              className="border border-[var(--rule)] rounded-[5px] bg-[var(--surface)]"
            >
              <div className="border-b border-[var(--rule)] px-4 py-2.5 flex items-center justify-between">
                <span className="mono-label">BEARER TOKEN</span>
                <button
                  type="button"
                  onClick={() => setShowToken((v) => !v)}
                  className="inline-flex items-center gap-1 text-[11px] text-[var(--ink-muted)] hover:text-[var(--ink-dim)]"
                >
                  {showToken ? (
                    <>
                      <EyeOff className="h-3 w-3" /> hide
                    </>
                  ) : (
                    <>
                      <Eye className="h-3 w-3" /> reveal
                    </>
                  )}
                </button>
              </div>
              <div className="px-4 py-3">
                <Input
                  type={showToken ? 'text' : 'password'}
                  autoFocus
                  invalid={Boolean(err)}
                  placeholder="sk-… or your configured API_TOKEN"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  className="font-mono text-[12.5px] h-9"
                />
                {err && (
                  <p className="mt-2 font-mono text-[11.5px] text-[var(--bad)] leading-tight">
                    {err}
                  </p>
                )}
              </div>
              <div className="border-t border-[var(--rule)] bg-[var(--surface-2)] px-4 py-2.5 flex items-center justify-between">
                <span className="font-mono text-[11px] text-[var(--ink-muted)]">
                  → checks <span className="text-[var(--ink-dim)]">/ready</span>
                </span>
                <Button
                  size="md"
                  type="submit"
                  disabled={submitting}
                  leading={<Lock className="h-3.5 w-3.5" />}
                >
                  {submitting ? 'Connecting…' : 'Connect'}
                </Button>
              </div>
            </form>

            <details className="mt-4 group">
              <summary className="cursor-pointer text-[11.5px] text-[var(--ink-muted)] hover:text-[var(--ink-dim)] inline-flex items-center gap-1.5 select-none">
                <span className="text-[var(--accent)]">+</span>
                where do I find my token?
              </summary>
              <div className="mt-2 rounded-[3px] border border-[var(--rule)] bg-[var(--surface)] px-3 py-2.5 text-[12px] text-[var(--ink-dim)] leading-relaxed">
                Set{' '}
                <code className="font-mono text-[11px] text-[var(--ink)]">
                  API_TOKEN
                </code>{' '}
                in the backend{' '}
                <code className="font-mono text-[11px] text-[var(--ink)]">
                  .env
                </code>
                . The FastAPI startup log prints the active token. The token is
                sent as{' '}
                <code className="font-mono text-[11px] text-[var(--ink)]">
                  Authorization: Bearer …
                </code>{' '}
                on every API request.
              </div>
            </details>
          </div>
        </div>

        <footer className="flex h-9 items-center justify-between border-t border-[var(--rule)] px-5 font-mono text-[10.5px] text-[var(--ink-muted)]">
          <span>50 issuers · 337 filings · sec ed.</span>
          <span>
            <span className="text-[var(--ok)]">●</span> session ephemeral
          </span>
        </footer>
      </div>
    </div>
  )
}
