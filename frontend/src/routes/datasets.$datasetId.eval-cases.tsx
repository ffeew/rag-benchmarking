import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ClipboardList, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast, toastApiError } from '#/providers/ToastProvider'

import { Badge } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardBody, CardHeader } from '#/components/ui/card'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTrigger,
} from '#/components/ui/dialog'
import { Input, Select, Textarea } from '#/components/ui/input'
import { Label } from '#/components/ui/label'
import { Pagination } from '#/components/ui/pagination'
import { Skeleton } from '#/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '#/components/ui/table'
import { EmptyState } from '#/components/data/EmptyState'
import { ErrorState } from '#/components/data/ErrorState'
import { api } from '#/lib/api'
import type { EvalCase } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import { useToken } from '#/providers/TokenProvider'

export const Route = createFileRoute('/datasets/$datasetId/eval-cases')({
  component: EvalCasesPage,
})

const CATEGORIES = [
  'single_company_lookup',
  'table_lookup',
  'trend',
  'cross_company_comparison',
  'sector_synthesis',
  'multi_part',
  'latest_filing',
  'ambiguous',
  'insufficient_evidence',
] as const

const DIFFICULTIES = ['easy', 'medium', 'hard'] as const

function EvalCasesPage() {
  const { datasetId } = Route.useParams()
  const { token, isAuthed } = useToken()
  const [category, setCategory] = useState<string>('')
  const [difficulty, setDifficulty] = useState<string>('')
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)

  const params = {
    datasetId,
    category: category || undefined,
    difficulty: difficulty || undefined,
    limit,
    offset,
  }

  const casesQuery = useQuery({
    queryKey: qk.evalCases.list(params),
    queryFn: () =>
      api.evalCases(token, {
        dataset_id: datasetId,
        category: category || undefined,
        difficulty: difficulty || undefined,
        limit,
        offset,
      }),
    enabled: isAuthed,
    placeholderData: keepPreviousData,
  })

  const items = casesQuery.data?.items ?? []
  const total = casesQuery.data?.total ?? 0

  return (
    <div className="mx-auto max-w-[1440px] px-6 py-6 grid gap-5">
      <Card>
        <CardHeader
          title={
            <span>
              EVAL CASES{' '}
              <span className="font-mono numeric text-[var(--ink-muted)]">
                {total}
              </span>
            </span>
          }
          actions={<NewEvalCaseDialog datasetId={datasetId} />}
        />
        <CardBody padded={false}>
          <div className="grid gap-3 px-4 py-3 border-b border-[var(--rule)] sm:grid-cols-[180px_180px_1fr]">
            <div>
              <Label className="mono-label">CATEGORY</Label>
              <Select
                value={category}
                onChange={(e) => {
                  setCategory(e.target.value)
                  setOffset(0)
                }}
              >
                <option value="">all</option>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c.replace(/_/g, ' ')}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label className="mono-label">DIFFICULTY</Label>
              <Select
                value={difficulty}
                onChange={(e) => {
                  setDifficulty(e.target.value)
                  setOffset(0)
                }}
              >
                <option value="">all</option>
                {DIFFICULTIES.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {casesQuery.isLoading ? (
            <div className="p-4 grid gap-1.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-9" />
              ))}
            </div>
          ) : casesQuery.isError ? (
            <ErrorState
              error={casesQuery.error}
              onRetry={() => casesQuery.refetch()}
            />
          ) : items.length === 0 ? (
            <EmptyState
              icon={ClipboardList}
              title="No eval cases"
              description="Create a case manually or seed the curated set via the seed_eval_cases script."
            />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>CASE KEY</TH>
                  <TH>CATEGORY</TH>
                  <TH>DIFFICULTY</TH>
                  <TH>QUESTION</TH>
                  <TH>TAGS</TH>
                  <TH className="w-[40px]"></TH>
                </tr>
              </THead>
              <TBody>
                {items.map((c) => (
                  <CaseRow key={c.id} item={c} />
                ))}
              </TBody>
            </Table>
          )}
          <Pagination
            total={total}
            limit={limit}
            offset={offset}
            onChange={({ limit: nextLimit, offset: nextOffset }) => {
              setLimit(nextLimit)
              setOffset(nextOffset)
            }}
          />
        </CardBody>
      </Card>
    </div>
  )
}

function CaseRow({ item }: { item: EvalCase }) {
  const { token } = useToken()
  const queryClient = useQueryClient()
  const remove = useMutation({
    mutationFn: () => api.deleteEvalCase(token, item.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: qk.evalCases.all(),
      })
      toast.success(`Deleted ${item.case_key ?? item.id}`)
    },
    onError: (error) => toastApiError(error, 'Delete failed'),
  })
  return (
    <TR>
      <TD>
        <span className="font-mono text-[12px] text-[var(--ink)]">
          {item.case_key ?? <span className="text-[var(--ink-muted)]">—</span>}
        </span>
      </TD>
      <TD>
        {item.category ? (
          <Badge tone="cite" size="sm">
            {item.category.replace(/_/g, ' ')}
          </Badge>
        ) : (
          <span className="text-[var(--ink-muted)]">—</span>
        )}
      </TD>
      <TD>
        <span className="text-[12px] text-[var(--ink-dim)]">
          {item.difficulty ?? '—'}
        </span>
      </TD>
      <TD className="max-w-[480px]">
        <span className="text-[12px] text-[var(--ink)] line-clamp-2">
          {item.question}
        </span>
      </TD>
      <TD>
        <div className="flex flex-wrap gap-1">
          {item.tags.slice(0, 3).map((tag) => (
            <Badge key={tag} tone="neutral" size="sm">
              {tag}
            </Badge>
          ))}
        </div>
      </TD>
      <TD>
        <Button
          variant="ghost"
          size="xs"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(`Delete eval case ${item.case_key ?? item.id}?`)) {
              remove.mutate()
            }
          }}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </TD>
    </TR>
  )
}

function NewEvalCaseDialog({ datasetId }: { datasetId: string }) {
  const { token } = useToken()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    case_key: '',
    category: '',
    difficulty: '',
    question: '',
    expected_answer: '',
    tags: '',
  })

  const create = useMutation({
    mutationFn: () =>
      api.createEvalCase(token, {
        dataset_id: datasetId,
        case_key: form.case_key || undefined,
        category: form.category || undefined,
        difficulty: form.difficulty || undefined,
        question: form.question,
        expected_answer: form.expected_answer || null,
        tags: form.tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      toast.success('Eval case created')
      setOpen(false)
      setForm({
        case_key: '',
        category: '',
        difficulty: '',
        question: '',
        expected_answer: '',
        tags: '',
      })
      void queryClient.invalidateQueries({ queryKey: qk.evalCases.all() })
    },
    onError: (error) => toastApiError(error, 'Create failed'),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" leading={<Plus className="h-3.5 w-3.5" />}>
          New case
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader
          title="NEW EVAL CASE"
          subtitle="Add a curated case to the eval set. Case key must be unique per dataset."
        />
        <DialogBody className="grid gap-3">
          <div>
            <Label className="mono-label">CASE KEY (optional)</Label>
            <Input
              value={form.case_key}
              onChange={(e) =>
                setForm((f) => ({ ...f, case_key: e.target.value }))
              }
              placeholder="aapl_2025_revenue"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="mono-label">CATEGORY</Label>
              <Select
                value={form.category}
                onChange={(e) =>
                  setForm((f) => ({ ...f, category: e.target.value }))
                }
              >
                <option value="">—</option>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c.replace(/_/g, ' ')}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label className="mono-label">DIFFICULTY</Label>
              <Select
                value={form.difficulty}
                onChange={(e) =>
                  setForm((f) => ({ ...f, difficulty: e.target.value }))
                }
              >
                <option value="">—</option>
                {DIFFICULTIES.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div>
            <Label className="mono-label">QUESTION</Label>
            <Textarea
              value={form.question}
              onChange={(e) =>
                setForm((f) => ({ ...f, question: e.target.value }))
              }
              placeholder="What was AAPL's revenue in fiscal 2025?"
              rows={3}
            />
          </div>
          <div>
            <Label className="mono-label">EXPECTED ANSWER (optional)</Label>
            <Textarea
              value={form.expected_answer}
              onChange={(e) =>
                setForm((f) => ({ ...f, expected_answer: e.target.value }))
              }
              rows={2}
            />
          </div>
          <div>
            <Label className="mono-label">TAGS (comma-separated)</Label>
            <Input
              value={form.tags}
              onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
              placeholder="revenue, factual"
            />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!form.question.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? 'Creating…' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
