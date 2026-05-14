import { useMutation, useQueryClient } from '@tanstack/react-query'
import { File, UploadCloud, X } from 'lucide-react'
import { useState } from 'react'

import { Button } from '#/components/ui/button'
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTrigger,
} from '#/components/ui/sheet'
import { api } from '#/lib/api'
import { formatBytes } from '#/lib/format'
import { qk } from '#/lib/queryKeys'
import { toast, toastApiError } from '#/providers/ToastProvider'
import { useToken } from '#/providers/TokenProvider'

export function UploadSheet({
  datasetId,
  trigger,
}: {
  datasetId: string
  trigger?: React.ReactNode
}) {
  const { token } = useToken()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [files, setFiles] = useState<Array<File>>([])
  const [dragging, setDragging] = useState(false)

  const uploadMutation = useMutation({
    mutationFn: () => api.uploadDocuments(token, datasetId, files),
    onSuccess: (result) => {
      const count = result.documents.length
      const queued = result.queued_document_ids.length
      toast.success(
        `Uploaded ${count} document${count === 1 ? '' : 's'}`,
        queued > 0
          ? `Queued ${queued} ingestion job${queued === 1 ? '' : 's'}`
          : undefined,
      )
      void queryClient.invalidateQueries({ queryKey: qk.datasets.all() })
      void queryClient.invalidateQueries({
        queryKey: qk.datasets.documentsAll(datasetId),
      })
      void queryClient.invalidateQueries({ queryKey: qk.jobs.all() })
      setFiles([])
      setOpen(false)
    },
    onError: (err) => toastApiError(err, 'Upload failed'),
  })

  function addFiles(picked: FileList | Array<File>) {
    const next = Array.from(picked).filter(
      (f) => f.type === 'application/pdf' || f.name.endsWith('.pdf'),
    )
    setFiles((prev) => [...prev, ...next])
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        {trigger ?? (
          <Button
            variant="secondary"
            size="sm"
            leading={<UploadCloud className="h-3.5 w-3.5" />}
          >
            Upload
          </Button>
        )}
      </SheetTrigger>
      <SheetContent side="right" className="w-full sm:max-w-[480px]">
        <SheetHeader
          title="Upload PDFs"
          subtitle="Bulk-add PDFs to this dataset."
        />
        <SheetBody>
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              addFiles(e.dataTransfer.files)
            }}
            className={`flex flex-col items-center justify-center gap-2 rounded-[5px] border border-dashed px-6 py-8 text-center transition-colors ${
              dragging
                ? 'border-[var(--accent)] bg-[var(--accent-soft)]'
                : 'border-[var(--rule-strong)] bg-[var(--surface-2)]'
            }`}
          >
            <UploadCloud className="h-6 w-6 text-[var(--ink-muted)]" />
            <p className="text-[13px] text-[var(--ink-dim)]">
              Drag PDFs here or{' '}
              <label className="cursor-pointer text-[var(--accent)] hover:underline">
                browse
                <input
                  type="file"
                  multiple
                  accept="application/pdf"
                  className="sr-only"
                  onChange={(e) => e.target.files && addFiles(e.target.files)}
                />
              </label>
            </p>
            <p className="font-mono text-[10.5px] text-[var(--ink-muted)]">
              Only .pdf is accepted.
            </p>
          </div>

          {files.length > 0 && (
            <ul className="mt-4 grid gap-1.5">
              {files.map((f, i) => (
                <li
                  key={i}
                  className="flex items-center gap-2 rounded-[3px] border border-[var(--rule)] bg-[var(--surface)] px-2.5 py-1.5"
                >
                  <File className="h-3.5 w-3.5 text-[var(--ink-muted)]" />
                  <span className="flex-1 truncate text-[12px] text-[var(--ink)]">
                    {f.name}
                  </span>
                  <span className="font-mono numeric text-[10.5px] text-[var(--ink-muted)]">
                    {formatBytes(f.size)}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setFiles((prev) => prev.filter((_, idx) => idx !== i))
                    }
                    className="text-[var(--ink-muted)] hover:text-[var(--bad)]"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </SheetBody>
        <SheetFooter>
          <span className="mr-auto font-mono text-[11px] text-[var(--ink-muted)]">
            {files.length} file{files.length === 1 ? '' : 's'} ·{' '}
            {formatBytes(files.reduce((s, f) => s + f.size, 0))}
          </span>
          <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={files.length === 0 || uploadMutation.isPending}
            onClick={() => uploadMutation.mutate()}
          >
            {uploadMutation.isPending ? 'Uploading…' : `Upload ${files.length}`}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
