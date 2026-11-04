import type { DocumentStatusPayload, JobStatusResponse } from '@/api/client'
import type { components } from '@/api/schema'

type ProgressState = components['schemas']['ProgressState']

/** The progress bar tracks finished documents, not elapsed time. */
export function progressPercent(status: JobStatusResponse | null): number {
  if (!status || status.documents_total <= 0) {
    return 0
  }
  const ratio = (status.documents_completed / status.documents_total) * 100
  return Math.min(100, Math.max(0, Math.round(ratio)))
}

/** The document the pipeline is on now, or the next one it will pick up. */
export function activeDocument(
  status: JobStatusResponse | null,
): DocumentStatusPayload | null {
  if (!status) {
    return null
  }
  return (
    status.documents.find((document) => document.state === 'processing') ??
    status.documents.find((document) => document.state === 'pending') ??
    null
  )
}

export function currentStageName(document: DocumentStatusPayload | null): string | null {
  if (!document) {
    return null
  }
  return document.stages.find((stage) => stage.status === 'processing')?.name ?? null
}

/** Keep each completed document's five real stage statuses visible during the job. */
export function showsStages(document: DocumentStatusPayload): boolean {
  return document.state !== 'pending'
}

const STATE_LABELS: Record<ProgressState, string> = {
  pending: 'Pending',
  processing: 'Processing',
  completed: 'Completed',
  failed: 'Failed',
}

export function stateLabel(state: ProgressState): string {
  return STATE_LABELS[state]
}
