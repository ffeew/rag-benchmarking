import { zodResolver } from '#/lib/zodResolver'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Database, FolderInput } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { Button } from '#/components/ui/button'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTrigger,
} from '#/components/ui/dialog'
import { Field } from '#/components/ui/field'
import { Input, Textarea } from '#/components/ui/input'
import { Switch } from '#/components/ui/switch'
import { api } from '#/lib/api'
import { splitCsv } from '#/lib/filters'
import { qk } from '#/lib/queryKeys'
import { paths } from '#/lib/routes'
import { toast, toastApiError } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

const schema = z.object({
  name: z.string().min(1, 'Required'),
  description: z.string().optional(),
  populate_from_corpus: z.boolean(),
  path: z.string().optional(),
  // Optional dataset overrides — surfaced behind a collapsible "Advanced" section.
  domain_label: z.string().optional(),
  entity_label: z.string().optional(),
  valid_forms: z.string().optional(),
  metric_terms: z.string().optional(),
  hyde_style_hint: z.string().optional(),
  citation_label_template: z.string().optional(),
})

type FormValues = z.infer<typeof schema>

export function NewDatasetDialog({ trigger }: { trigger?: React.ReactNode }) {
  const { token } = useToken()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  const [showAdvanced, setShowAdvanced] = useState(false)
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      description: '',
      populate_from_corpus: false,
      path: '',
      domain_label: '',
      entity_label: '',
      valid_forms: '',
      metric_terms: '',
      hyde_style_hint: '',
      citation_label_template: '',
    },
  })

  const populate = form.watch('populate_from_corpus')

  const createMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const overrides = {
        domain_label: values.domain_label?.trim() || undefined,
        entity_label: values.entity_label?.trim() || undefined,
        valid_forms: splitCsv(values.valid_forms),
        metric_terms: splitCsv(values.metric_terms),
        hyde_style_hint: values.hyde_style_hint?.trim() || undefined,
        citation_label_template:
          values.citation_label_template?.trim() || undefined,
      }
      if (values.populate_from_corpus) {
        const result = await api.registerLocalCorpus(token, {
          dataset_name: values.name,
          description: values.description || undefined,
          path: values.path || undefined,
          ...overrides,
        })
        return {
          dataset: result.dataset,
          queuedCount: result.queued_document_ids.length,
        }
      }
      const dataset = await api.createDataset(token, {
        name: values.name,
        description: values.description || undefined,
        ...overrides,
      })
      return { dataset, queuedCount: 0 }
    },
    onSuccess: ({ dataset, queuedCount }) => {
      void queryClient.invalidateQueries({ queryKey: qk.datasets.all() })
      void queryClient.invalidateQueries({
        queryKey: qk.datasets.documentsAll(dataset.id),
      })
      void queryClient.invalidateQueries({ queryKey: qk.jobs.all() })
      toast.success(
        `Created dataset "${dataset.name}"`,
        queuedCount > 0
          ? `Queued ${queuedCount} ingestion job${queuedCount === 1 ? '' : 's'}`
          : undefined,
      )
      setOpen(false)
      form.reset()
      void navigate(paths.dataset(dataset.id))
    },
    onError: (err) => toastApiError(err, 'Failed to create dataset'),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button leading={<Database className="h-3.5 w-3.5" />}>
            New dataset
          </Button>
        )}
      </DialogTrigger>
      <DialogContent size="md">
        <form
          onSubmit={form.handleSubmit((values) =>
            createMutation.mutate(values),
          )}
          className="contents"
        >
          <DialogHeader
            title="New dataset"
            subtitle="A dataset is a namespace for documents and ingestion runs."
          />
          <DialogBody className="grid gap-4">
            <Field
              label="NAME"
              required
              error={form.formState.errors.name?.message}
              htmlFor="ds-name"
            >
              <Input
                id="ds-name"
                placeholder="sec-filings"
                autoFocus
                invalid={Boolean(form.formState.errors.name)}
                {...form.register('name')}
              />
            </Field>
            <Field label="DESCRIPTION" htmlFor="ds-desc">
              <Textarea
                id="ds-desc"
                placeholder="Brief description of this dataset."
                className="min-h-[64px]"
                {...form.register('description')}
              />
            </Field>
            <div className="border-t border-[var(--rule)] pt-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[13px] font-medium text-[var(--ink)] flex items-center gap-2">
                    <FolderInput className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                    Import from local corpus
                  </div>
                  <p className="text-[11.5px] text-[var(--ink-muted)] mt-0.5">
                    Bulk-registers PDFs from the server&apos;s configured corpus
                    folder.
                  </p>
                </div>
                <Switch
                  checked={populate}
                  onCheckedChange={(v) =>
                    form.setValue('populate_from_corpus', Boolean(v))
                  }
                />
              </div>
              {populate && (
                <div className="mt-3">
                  <Field
                    label="CORPUS PATH (optional)"
                    hint="Overrides LOCAL_CORPUS_PATH for this import."
                    htmlFor="ds-path"
                  >
                    <Input
                      id="ds-path"
                      placeholder="/data/sec_filings_pdf"
                      {...form.register('path')}
                    />
                  </Field>
                </div>
              )}
            </div>
            <div className="border-t border-[var(--rule)] pt-4">
              <button
                type="button"
                onClick={() => setShowAdvanced((value) => !value)}
                className="text-[12.5px] font-medium text-[var(--ink-dim)] hover:text-[var(--ink)]"
              >
                {showAdvanced ? '▾' : '▸'} Advanced — domain overrides (optional)
              </button>
              <p className="text-[11.5px] text-[var(--ink-muted)] mt-1">
                Customize how the planner/HyDE/generator describe this corpus.
                Leave blank to use SEC defaults.
              </p>
              {showAdvanced && (
                <div className="mt-3 grid gap-3">
                  <Field
                    label="DOMAIN LABEL"
                    hint='e.g. "SEC filings of US public companies"'
                    htmlFor="ds-domain-label"
                  >
                    <Input
                      id="ds-domain-label"
                      placeholder="SEC filings of US public companies"
                      {...form.register('domain_label')}
                    />
                  </Field>
                  <Field
                    label="ENTITY LABEL"
                    hint='e.g. "ticker", "CUSIP", "drug name"'
                    htmlFor="ds-entity-label"
                  >
                    <Input
                      id="ds-entity-label"
                      placeholder="ticker"
                      {...form.register('entity_label')}
                    />
                  </Field>
                  <Field
                    label="VALID FORMS (comma separated)"
                    hint='e.g. "10-K, 10-Q, 8-K"'
                    htmlFor="ds-valid-forms"
                  >
                    <Input
                      id="ds-valid-forms"
                      placeholder="10-K, 10-Q, 8-K"
                      {...form.register('valid_forms')}
                    />
                  </Field>
                  <Field
                    label="METRIC TERMS (comma separated)"
                    hint="Words the planner uses to identify metric-seeking questions."
                    htmlFor="ds-metric-terms"
                  >
                    <Input
                      id="ds-metric-terms"
                      placeholder="revenue, debt, cash"
                      {...form.register('metric_terms')}
                    />
                  </Field>
                  <Field
                    label="HYDE STYLE HINT"
                    hint="Corpus-style guidance for HyDE passage generation."
                    htmlFor="ds-hyde-style"
                  >
                    <Textarea
                      id="ds-hyde-style"
                      placeholder="Formal financial filing tone with numeric tables."
                      className="min-h-[48px]"
                      {...form.register('hyde_style_hint')}
                    />
                  </Field>
                  <Field
                    label="CITATION TEMPLATE"
                    hint="Allowed placeholders: {entity} {filing_date} {form_type} {page}"
                    htmlFor="ds-citation-template"
                  >
                    <Input
                      id="ds-citation-template"
                      placeholder="[{entity} {filing_date} {form_type}, p. {page}]"
                      {...form.register('citation_label_template')}
                    />
                  </Field>
                </div>
              )}
            </div>
          </DialogBody>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={createMutation.isPending}>
              {createMutation.isPending
                ? 'Creating…'
                : populate
                  ? 'Create & import'
                  : 'Create dataset'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
