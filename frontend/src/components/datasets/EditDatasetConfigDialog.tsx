import { zodResolver } from '#/lib/zodResolver'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Settings as SettingsIcon } from 'lucide-react'
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
import { api } from '#/lib/api'
import type { Dataset } from '#/lib/api'
import { qk } from '#/lib/queryKeys'
import { toast, toastApiError } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

/**
 * Edits the per-dataset retrieval overrides used by the planner / HyDE / verifier /
 * generator / retrieval agents and the deterministic heuristic-planner fallback.
 *
 * Every field is optional: a blank value clears the override and re-enables the
 * SEC fallback at the next query. Comma-separated entries are parsed into arrays
 * for `valid_forms` and `metric_terms`.
 */

const schema = z.object({
  domain_label: z.string(),
  entity_label: z.string(),
  valid_forms: z.string(),
  metric_terms: z.string(),
  hyde_style_hint: z.string(),
  citation_label_template: z.string(),
})

type FormValues = z.infer<typeof schema>

function splitCsv(value: string): string[] | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  return trimmed
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function blankToNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function listToCsv(value: string[] | null | undefined): string {
  return value ? value.join(', ') : ''
}

export function EditDatasetConfigDialog({
  dataset,
  trigger,
}: {
  dataset: Dataset
  trigger?: React.ReactNode
}) {
  const { token } = useToken()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      domain_label: dataset.domain_label ?? '',
      entity_label: dataset.entity_label ?? '',
      valid_forms: listToCsv(dataset.valid_forms),
      metric_terms: listToCsv(dataset.metric_terms),
      hyde_style_hint: dataset.hyde_style_hint ?? '',
      citation_label_template: dataset.citation_label_template ?? '',
    },
  })

  const updateMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      return await api.patchDataset(token, dataset.id, {
        domain_label: blankToNull(values.domain_label),
        entity_label: blankToNull(values.entity_label),
        valid_forms: splitCsv(values.valid_forms),
        metric_terms: splitCsv(values.metric_terms),
        hyde_style_hint: blankToNull(values.hyde_style_hint),
        citation_label_template: blankToNull(values.citation_label_template),
      })
    },
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: qk.datasets.all() })
      void queryClient.invalidateQueries({
        queryKey: qk.datasets.detail(updated.id),
      })
      toast.success('Dataset config updated')
      setOpen(false)
    },
    onError: (err) => toastApiError(err, 'Failed to update dataset config'),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button
            variant="ghost"
            size="xs"
            leading={<SettingsIcon className="h-3 w-3" />}
          >
            edit config
          </Button>
        )}
      </DialogTrigger>
      <DialogContent size="md">
        <form
          onSubmit={form.handleSubmit((values) =>
            updateMutation.mutate(values),
          )}
          className="contents"
        >
          <DialogHeader
            title="Edit dataset config"
            subtitle="Per-dataset overrides for the agent prompts and heuristic-planner fallback. Blank fields fall back to SEC defaults."
          />
          <DialogBody className="grid gap-4">
            <Field
              label="DOMAIN LABEL"
              hint="Short corpus identity injected as CORPUS: … in every agent prompt."
              htmlFor="ds-domain"
            >
              <Input
                id="ds-domain"
                placeholder="SEC filings of US public companies"
                {...form.register('domain_label')}
              />
            </Field>
            <Field
              label="ENTITY LABEL"
              hint="Name of the primary entity in this corpus (e.g. ticker, subject)."
              htmlFor="ds-entity"
            >
              <Input
                id="ds-entity"
                placeholder="ticker"
                {...form.register('entity_label')}
              />
            </Field>
            <Field
              label="VALID FORMS"
              hint="Comma-separated list of allowed form types (e.g. 10-K, 10-Q, 8-K)."
              htmlFor="ds-forms"
            >
              <Input
                id="ds-forms"
                placeholder="10-K, 10-Q, 8-K"
                {...form.register('valid_forms')}
              />
            </Field>
            <Field
              label="METRIC TERMS"
              hint="Comma-separated keywords for the heuristic-planner fallback."
              htmlFor="ds-metrics"
            >
              <Input
                id="ds-metrics"
                placeholder="revenue, debt, r&d, …"
                {...form.register('metric_terms')}
              />
            </Field>
            <Field
              label="HYDE STYLE HINT"
              hint="Optional dataset-specific style cue appended to HyDE prompts."
              htmlFor="ds-hyde"
            >
              <Textarea
                id="ds-hyde"
                placeholder="Formal corporate disclosure register…"
                className="min-h-[64px]"
                {...form.register('hyde_style_hint')}
              />
            </Field>
            <Field
              label="CITATION LABEL TEMPLATE"
              hint="str.format template with {entity}, {filing_date}, {form_type}, {page} placeholders."
              htmlFor="ds-citation"
            >
              <Input
                id="ds-citation"
                placeholder="[{entity} {filing_date} {form_type}, p. {page}]"
                {...form.register('citation_label_template')}
              />
            </Field>
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
            <Button type="submit" size="sm" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? 'Saving…' : 'Save config'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
