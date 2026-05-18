import { api } from '#/lib/api'
import { toast, toastApiError } from '#/providers/ToastProvider'

export async function openSourcePdf(args: {
  token: string
  documentId: string
  page: number
}) {
  // Open the tab synchronously to keep the user-gesture context — otherwise
  // popup blockers fire on the post-await window.open call.
  // NOTE: Don't include `noopener` in the features string — by spec that makes
  // window.open return null, which would falsely trigger our popup-blocked path.
  const placeholder = window.open('about:blank', '_blank')
  if (!placeholder) {
    toast.error('Popup blocked', 'Allow pop-ups for this site to open PDFs.')
    return
  }
  // Sever the opener link manually so the new tab can't navigate back to us.
  try {
    placeholder.opener = null
  } catch {
    /* some browsers disallow assigning opener; safe to ignore */
  }
  try {
    const { url } = await api.documentFilePresignedUrl(
      args.token,
      args.documentId,
    )
    const page =
      Number.isFinite(args.page) && args.page > 0 ? Math.floor(args.page) : 1
    placeholder.location.href = `${url}#page=${page}`
  } catch (err) {
    placeholder.close()
    toastApiError(err, 'Could not open PDF')
  }
}
