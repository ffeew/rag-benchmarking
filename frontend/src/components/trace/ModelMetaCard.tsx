import { Card, CardBody, CardHeader } from '#/components/ui/card'
import { KeyValueGrid } from '#/components/data/KeyValueGrid'
import type { KVRow } from '#/components/data/KeyValueGrid'

export function ModelMetaCard({
  modelMetadata,
  finalAnswerMetadata,
}: {
  modelMetadata: Record<string, unknown>
  finalAnswerMetadata: Record<string, unknown>
}) {
  const merged: Record<string, unknown> = {
    ...modelMetadata,
    ...finalAnswerMetadata,
  }
  const rows: Array<KVRow> = []
  for (const [k, v] of Object.entries(merged)) {
    if (v == null || (typeof v === 'object' && Object.keys(v).length === 0))
      continue
    rows.push({
      key: k.replace(/_/g, ' '),
      value: typeof v === 'object' ? JSON.stringify(v) : String(v),
      mono: true,
      copyable: typeof v === 'string',
    })
  }

  if (rows.length === 0) return null

  return (
    <Card>
      <CardHeader title="MODELS & USAGE" />
      <CardBody>
        <KeyValueGrid rows={rows} dense />
      </CardBody>
    </Card>
  )
}
