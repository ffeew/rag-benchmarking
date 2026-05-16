import { zodResolver } from '#/lib/zodResolver'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Calendar, FileText, Hash, Save, Trash2 } from 'lucide-react'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { Badge, toneForStatus } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Field } from '#/components/ui/field'
import { Input } from '#/components/ui/input'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetFooter,
  SheetHeader,
} from '#/components/ui/sheet'
import { KeyValueGrid } from '#/components/data/KeyValueGrid'
import { api } from '#/lib/api'
import type { Document } from '#/lib/api'
import { formatBytes, formatDate } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { toast, toastApiError } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

const schema = z.object({
  ticker: z.string().min(1, 'Required'),
  company_name: z.string().optional().nullable(),
  form_type: z.string().min(1, 'Required'),
  filing_date: z.string().optional().nullable(),
  report_period: z.string().optional().nullable(),
  fiscal_year: z.string().optional(),
  fiscal_quarter: z.string().optional(),
})

type FormValues = z.output<typeof schema>

function parseOptionalInt(value: string | null | undefined): number | null {
  if (!value) return null
  const n = Number.parseInt(value, 10)
  return Number.isFinite(n) ? n : null
}

export function DocumentDrawer({
  document,
  open,
  onOpenChange,
}: {
  document: Document | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { token } = useToken()
  const queryClient = useQueryClient()

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaultsFor(document),
  })

  useEffect(() => {
    if (document) form.reset(defaultsFor(document))
  }, [document, form])

  const updateMutation = useMutation({
    mutationFn: (values: FormValues) => {
      if (!document) throw new Error('No document')
      return api.patchDocument(token, document.id, {
        ticker: values.ticker,
        company_name: values.company_name ?? null,
        form_type: values.form_type,
        filing_date: values.filing_date || null,
        report_period: values.report_period || null,
        fiscal_year: parseOptionalInt(values.fiscal_year),
        fiscal_quarter: parseOptionalInt(values.fiscal_quarter),
      })
    },
    onSuccess: () => {
      toast.success('Document updated')
      // Scope the invalidation to this dataset's documents/jobs instead of the
      // entire `datasets` tree (which would refetch every other dataset's data).
      if (document) {
        void queryClient.invalidateQueries({
          queryKey: qk.datasets.documentsAll(document.dataset_id),
        })
        void queryClient.invalidateQueries({
          queryKey: qk.datasets.detail(document.dataset_id),
        })
      }
      onOpenChange(false)
    },
    onError: (err) => toastApiError(err, 'Update failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: () => {
      if (!document) throw new Error('No document')
      return api.deleteDocument(token, document.id)
    },
    onSuccess: () => {
      toast.success('Document deleted')
      if (document) {
        void queryClient.invalidateQueries({
          queryKey: qk.datasets.documentsAll(document.dataset_id),
        })
        void queryClient.invalidateQueries({
          queryKey: qk.datasets.detail(document.dataset_id),
        })
      }
      onOpenChange(false)
    },
    onError: (err) => toastApiError(err, 'Delete failed'),
  })

  if (!document) return null

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-[520px]">
        <SheetHeader
          title={
            <span className="flex items-center gap-2">
              <FileText className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
              {document.ticker} · {document.form_type}
            </span>
          }
          subtitle={
            <span className="flex items-center gap-2">
              <Badge tone={toneForStatus(document.ingestion_status)} size="sm">
                {document.ingestion_status ?? 'NEW'}
              </Badge>
              <span className="font-mono text-[10.5px] text-[var(--ink-muted)]">
                {document.id.slice(0, 10)}…
              </span>
            </span>
          }
        />
        <SheetBody className="grid gap-5">
          <form
            id="doc-edit"
            className="grid gap-3"
            onSubmit={form.handleSubmit((v) => updateMutation.mutate(v))}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <Field
                label="TICKER"
                required
                error={form.formState.errors.ticker?.message}
              >
                <Input
                  invalid={Boolean(form.formState.errors.ticker)}
                  {...form.register('ticker')}
                />
              </Field>
              <Field
                label="FORM"
                required
                error={form.formState.errors.form_type?.message}
              >
                <Input
                  invalid={Boolean(form.formState.errors.form_type)}
                  {...form.register('form_type')}
                />
              </Field>
            </div>
            <Field label="COMPANY NAME">
              <Input {...form.register('company_name')} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="FILING DATE" hint="YYYY-MM-DD">
                <Input
                  type="date"
                  leading={<Calendar className="h-3 w-3" />}
                  {...form.register('filing_date')}
                />
              </Field>
              <Field label="REPORT PERIOD" hint="YYYY-MM-DD">
                <Input
                  type="date"
                  leading={<Calendar className="h-3 w-3" />}
                  {...form.register('report_period')}
                />
              </Field>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="FISCAL YEAR">
                <Input
                  type="number"
                  placeholder="2024"
                  leading={<Hash className="h-3 w-3" />}
                  {...form.register('fiscal_year')}
                />
              </Field>
              <Field label="FISCAL QUARTER" hint="1–4">
                <Input
                  type="number"
                  min={1}
                  max={4}
                  placeholder="—"
                  {...form.register('fiscal_quarter')}
                />
              </Field>
            </div>
          </form>

          <div className="border-t border-[var(--rule)] pt-4">
            <div className="mono-label mb-2">FILE</div>
            <KeyValueGrid
              dense
              rows={[
                {
                  key: 'checksum',
                  value: document.checksum,
                  mono: true,
                  copyable: true,
                },
                {
                  key: 'size',
                  value: formatBytes(document.byte_size),
                  mono: true,
                },
                { key: 'bucket', value: document.minio_bucket, mono: true },
                {
                  key: 'key',
                  value: document.minio_key,
                  mono: true,
                  copyable: true,
                },
                {
                  key: 'version',
                  value: document.minio_version_id ?? '—',
                  mono: true,
                },
                { key: 'created', value: formatDate(document.created_at) },
              ]}
            />
          </div>
        </SheetBody>
        <SheetFooter>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            leading={<Trash2 className="h-3.5 w-3.5" />}
            onClick={() => {
              if (
                confirm(
                  `Delete ${document.ticker} ${document.form_type}? Chunks will be removed.`,
                )
              ) {
                deleteMutation.mutate()
              }
            }}
            disabled={deleteMutation.isPending}
          >
            Delete
          </Button>
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              form="doc-edit"
              size="sm"
              leading={<Save className="h-3.5 w-3.5" />}
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function defaultsFor(doc: Document | null): FormValues {
  return {
    ticker: doc?.ticker ?? '',
    company_name: doc?.company_name ?? '',
    form_type: doc?.form_type ?? '',
    filing_date: doc?.filing_date ?? '',
    report_period: doc?.report_period ?? '',
    fiscal_year: doc?.fiscal_year != null ? String(doc.fiscal_year) : '',
    fiscal_quarter:
      doc?.fiscal_quarter != null ? String(doc.fiscal_quarter) : '',
  }
}
