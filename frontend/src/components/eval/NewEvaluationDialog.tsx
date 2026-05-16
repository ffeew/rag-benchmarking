import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Download, Package, Play } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Badge } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Checkbox } from '#/components/ui/checkbox'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTrigger,
} from '#/components/ui/dialog'
import { Field } from '#/components/ui/field'
import { Input, Select, Textarea } from '#/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '#/components/ui/tabs'
import { api, RETRIEVAL_MODES } from '#/lib/api'
import type { EvalCase, EvalPackSummary, RetrievalMode } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { toast, toastApiError } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

export function NewEvaluationDialog({ datasetId }: { datasetId: string }) {
  const { token } = useToken()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  const [tab, setTab] = useState<'library' | 'inline'>('library')
  const [questions, setQuestions] = useState(
    "What was Microsoft's total revenue in FY2024?\nWhat is Tesla's current long-term debt as reported in their latest 10-K?",
  )
  const [expected, setExpected] = useState('')
  const [benchmarkProfile, setBenchmarkProfile] = useState<
    'scientific' | 'diagnostic'
  >('diagnostic')
  const [variants, setVariants] = useState<Array<RetrievalMode>>([
    ...RETRIEVAL_MODES,
  ])
  const [selectedCaseIds, setSelectedCaseIds] = useState<Array<string>>([])

  const casesQuery = useQuery({
    queryKey: qk.evalCases.list({ datasetId, limit: 200 }),
    queryFn: () =>
      api
        .evalCases(token, { dataset_id: datasetId, limit: 200 })
        .then((page) => page.items)
        .catch(() => [] as Array<EvalCase>),
    enabled: open,
  })

  const packsQuery = useQuery({
    queryKey: qk.evalPacks.list(),
    queryFn: () => api.evalPacks(token).catch(() => [] as Array<EvalPackSummary>),
    enabled: open,
  })

  useEffect(() => {
    if (!open) {
      setSelectedCaseIds([])
    }
  }, [open])

  const parsedQuestions = useMemo(
    () =>
      questions
        .split('\n')
        .map((q) => q.trim())
        .filter(Boolean),
    [questions],
  )

  const libraryCases = casesQuery.data ?? []
  const allPacks = packsQuery.data ?? []

  // Map gold_version -> pack so library rows can render a BUNDLED · <pack_id> badge.
  const packsByGoldVersion = useMemo(() => {
    const map = new Map<string, EvalPackSummary>()
    for (const pack of allPacks) {
      if (pack.gold_version) map.set(pack.gold_version, pack)
    }
    return map
  }, [allPacks])

  // Packs that aren't fully present in the library for this dataset yet.
  const importablePacks = useMemo(() => {
    const libraryCountByGoldVersion = new Map<string, number>()
    for (const c of libraryCases) {
      if (!c.gold_version) continue
      libraryCountByGoldVersion.set(
        c.gold_version,
        (libraryCountByGoldVersion.get(c.gold_version) ?? 0) + 1,
      )
    }
    return allPacks.filter((pack) => {
      const present = pack.gold_version
        ? libraryCountByGoldVersion.get(pack.gold_version) ?? 0
        : 0
      return present < pack.case_count
    })
  }, [allPacks, libraryCases])

  const importMutation = useMutation({
    mutationFn: (packId: string) =>
      api.importEvalPack(token, packId, { dataset_id: datasetId }),
    onSuccess: (resp) => {
      const total = resp.created + resp.updated
      toast.success(
        `Imported ${total} bundled case${total === 1 ? '' : 's'}`,
      )
      void queryClient.invalidateQueries({ queryKey: qk.evalCases.all() })
      setSelectedCaseIds(resp.case_ids)
      setBenchmarkProfile('scientific')
      setTab('library')
    },
    onError: (err) => toastApiError(err, 'Failed to import bundled pack'),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.createEvaluation(token, {
        dataset_id: datasetId,
        system_variants: variants,
        benchmark_profile: benchmarkProfile,
        cases:
          tab === 'inline'
            ? parsedQuestions.map((q) => ({
                question: q,
                expected_answer: expected || undefined,
                tags: ['manual'],
              }))
            : undefined,
        case_ids: tab === 'library' ? selectedCaseIds : undefined,
      }),
    onSuccess: (result) => {
      toast.success('Evaluation queued')
      void queryClient.invalidateQueries({ queryKey: qk.evaluations.all() })
      void queryClient.invalidateQueries({ queryKey: qk.jobs.all() })
      setOpen(false)
      void navigate(paths.evaluation(datasetId, result.eval_run_id))
    },
    onError: (err) => toastApiError(err, 'Failed to start evaluation'),
  })

  function toggleCase(id: string) {
    setSelectedCaseIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  function toggleVariant(v: RetrievalMode) {
    setVariants((prev) =>
      prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v],
    )
  }

  function selectAllLibrary() {
    setSelectedCaseIds(libraryCases.map((c) => c.id))
  }

  const valid =
    variants.length > 0 &&
    ((tab === 'inline' && parsedQuestions.length > 0) ||
      (tab === 'library' && selectedCaseIds.length > 0))

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button leading={<Play className="h-3.5 w-3.5" />}>
          New evaluation
        </Button>
      </DialogTrigger>
      <DialogContent size="lg">
        <DialogHeader
          title="New evaluation"
          subtitle="Run the same case set against one or more retrieval modes."
        />
        <DialogBody className="grid gap-4">
          <Tabs
            value={tab}
            onValueChange={(v) => setTab(v as 'library' | 'inline')}
          >
            <TabsList>
              <TabsTrigger value="library">
                FROM LIBRARY
                {casesQuery.data && (
                  <Badge tone="neutral" size="sm">
                    {casesQuery.data.length}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="inline">INLINE CASES</TabsTrigger>
            </TabsList>
            <TabsContent value="library" className="grid gap-2">
              {importablePacks.length > 0 && (
                <div className="grid gap-2">
                  {importablePacks.map((pack) => (
                    <PackImportCallout
                      key={pack.id}
                      pack={pack}
                      pending={
                        importMutation.isPending &&
                        importMutation.variables === pack.id
                      }
                      onImport={() => importMutation.mutate(pack.id)}
                    />
                  ))}
                </div>
              )}
              {casesQuery.isLoading ? (
                <p className="text-[12.5px] text-[var(--ink-muted)]">
                  Loading cases…
                </p>
              ) : libraryCases.length === 0 ? (
                importablePacks.length === 0 && (
                  <p className="rounded-[3px] border border-dashed border-[var(--rule)] px-3 py-6 text-center text-[12.5px] text-[var(--ink-muted)]">
                    No eval cases yet. Add cases via the eval cases page or
                    paste inline questions in the other tab.
                  </p>
                )
              ) : (
                <>
                  <div className="flex items-center justify-between px-1">
                    <span className="font-mono text-[10.5px] text-[var(--ink-muted)]">
                      {selectedCaseIds.length} of {libraryCases.length} selected
                    </span>
                    <button
                      type="button"
                      onClick={selectAllLibrary}
                      className="font-mono text-[10.5px] text-[var(--accent)] hover:underline"
                    >
                      Select all
                    </button>
                  </div>
                  <ul className="max-h-[260px] overflow-y-auto rounded-[3px] border border-[var(--rule)] bg-[var(--surface)]">
                    {libraryCases.map((c) => {
                      const bundledPack = c.gold_version
                        ? packsByGoldVersion.get(c.gold_version)
                        : undefined
                      return (
                        <li
                          key={c.id}
                          className="flex items-start gap-3 border-b last:border-b-0 border-[var(--rule)] px-3 py-2"
                        >
                          <Checkbox
                            checked={selectedCaseIds.includes(c.id)}
                            onCheckedChange={() => toggleCase(c.id)}
                            className="mt-0.5"
                          />
                          <div className="min-w-0 flex-1">
                            <p className="text-[12.5px] text-[var(--ink)]">
                              {c.question}
                            </p>
                            {c.expected_answer && (
                              <p className="mt-0.5 font-mono text-[10.5px] text-[var(--ink-muted)]">
                                expected: {c.expected_answer.slice(0, 80)}
                              </p>
                            )}
                          </div>
                          <div className="flex flex-col items-end gap-1">
                            {bundledPack && (
                              <Badge tone="cite" size="sm">
                                BUNDLED · {bundledPack.id}
                              </Badge>
                            )}
                            {c.tags.length > 0 && (
                              <div className="flex flex-wrap justify-end gap-1">
                                {c.tags.slice(0, 3).map((t) => (
                                  <Badge key={t} tone="neutral" size="sm">
                                    {t}
                                  </Badge>
                                ))}
                              </div>
                            )}
                          </div>
                        </li>
                      )
                    })}
                  </ul>
                </>
              )}
            </TabsContent>
            <TabsContent value="inline" className="grid gap-3">
              <Field label="QUESTIONS" hint="One per line">
                <Textarea
                  rows={6}
                  value={questions}
                  onChange={(e) => setQuestions(e.target.value)}
                  className="min-h-[120px] font-mono text-[12.5px]"
                />
                <span className="font-mono text-[10.5px] text-[var(--ink-muted)]">
                  {parsedQuestions.length} case
                  {parsedQuestions.length === 1 ? '' : 's'}
                </span>
              </Field>
              <Field
                label="EXPECTED SUBSTRING (optional)"
                hint="Applied to all inline cases"
              >
                <Input
                  value={expected}
                  onChange={(e) => setExpected(e.target.value)}
                  placeholder="e.g. $5.2 billion"
                />
              </Field>
            </TabsContent>
          </Tabs>

          <Field label="BENCHMARK PROFILE">
            <Select
              value={benchmarkProfile}
              onChange={(e) =>
                setBenchmarkProfile(e.target.value as 'scientific' | 'diagnostic')
              }
            >
              <option value="diagnostic">diagnostic</option>
              <option value="scientific">scientific</option>
            </Select>
          </Field>

          <div className="border-t border-[var(--rule)] pt-3">
            <div className="mono-label mb-2">VARIANTS</div>
            <div className="flex flex-wrap gap-2">
              {RETRIEVAL_MODES.map((v) => {
                const active = variants.includes(v)
                return (
                  <button
                    type="button"
                    key={v}
                    onClick={() => toggleVariant(v)}
                    className={`inline-flex items-center gap-1.5 rounded-[3px] border px-2.5 py-1 font-mono text-[11.5px] transition-colors ${
                      active
                        ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]'
                        : 'border-[var(--rule-strong)] bg-[var(--surface-2)] text-[var(--ink-muted)]'
                    }`}
                  >
                    <Checkbox
                      checked={active}
                      onCheckedChange={() => toggleVariant(v)}
                    />
                    {v.replace('_', ' ')}
                  </button>
                )
              })}
            </div>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!valid || createMutation.isPending}
            onClick={() => createMutation.mutate()}
            leading={<Play className="h-3.5 w-3.5" />}
          >
            {createMutation.isPending ? 'Queuing…' : 'Run evaluation'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function PackImportCallout({
  pack,
  pending,
  onImport,
}: {
  pack: EvalPackSummary
  pending: boolean
  onImport: () => void
}) {
  return (
    <div className="flex items-start gap-3 rounded-[3px] border border-[var(--accent)] bg-[var(--accent-soft)] px-3 py-3">
      <Package className="mt-0.5 h-4 w-4 text-[var(--accent)]" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[12px] text-[var(--ink)]">
            {pack.id}
          </span>
          <Badge tone="cite" size="sm">
            BUNDLED
          </Badge>
        </div>
        <p className="mt-1 text-[12px] text-[var(--ink-dim)]">
          {pack.case_count} case{pack.case_count === 1 ? '' : 's'} ·{' '}
          {pack.verified_count} verified
          {pack.categories.length > 0 && (
            <>
              {' · '}
              {pack.categories.length} categor
              {pack.categories.length === 1 ? 'y' : 'ies'}
            </>
          )}
        </p>
        <p className="mt-1 font-mono text-[10.5px] text-[var(--ink-muted)]">
          Import to this dataset to run the curated benchmark. Re-importing is
          safe (idempotent upsert by case_key).
        </p>
      </div>
      <Button
        size="sm"
        disabled={pending}
        onClick={onImport}
        leading={<Download className="h-3.5 w-3.5" />}
      >
        {pending ? 'Importing…' : `Import ${pack.case_count}`}
      </Button>
    </div>
  )
}
