import type { DocumentStatusPayload, JobStatusResponse } from '@/api/client'
import {
  activeDocument,
  currentStageName,
  progressPercent,
  showsStages,
  stateLabel,
} from '@/workflow/status'

export function ProcessingStage({
  status,
  connectionInterrupted,
}: {
  status: JobStatusResponse | null
  connectionInterrupted: boolean
}) {
  const total = status?.documents_total ?? 0
  const completed = status?.documents_completed ?? 0
  const percent = progressPercent(status)
  const active = activeDocument(status)
  const stage = currentStageName(active)

  return (
    <section className="processing" aria-labelledby="processing-heading">
      <div className="processing__head">
        <h1 id="processing-heading" className="processing__title">
          {total > 0
            ? `Checking ${total} ${total === 1 ? 'quotation' : 'quotations'}`
            : 'Starting the run'}
        </h1>
        <p className="processing__count">
          {completed} / {total}
        </p>
      </div>

      <div
        className="progress"
        role="progressbar"
        aria-label="Documents finished"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span className="progress__fill" style={{ width: `${percent}%` }} />
      </div>

      <p className="processing__hint" aria-live="polite">
        {processingHint(status, active?.filename ?? null, stage)}
      </p>

      {connectionInterrupted ? (
        <p className="connection-notice" role="status">
          Connection interrupted. Your job is still saved; reconnecting automatically and keeping its progress.
        </p>
      ) : null}

      {total > 0 ? (
        <ol className="documents">
          {(status?.documents ?? []).map((document) => (
            <DocumentRow key={document.id} document={document} />
          ))}
        </ol>
      ) : null}
    </section>
  )
}

function DocumentRow({ document }: { document: DocumentStatusPayload }) {
  return (
    <li className="document">
      <div className="document__head">
        <p className="document__name" title={document.filename}>
          {document.filename}
        </p>
        <p className="document__state" data-state={document.state}>
          {stateLabel(document.state)}
        </p>
      </div>

      {showsStages(document) ? (
        <ol className="stages">
          {document.stages.map((stage) => (
            <li key={stage.name} className="stage" data-status={stage.status}>
              <span className="stage__mark" aria-hidden="true" />
              <span>{stage.name}</span>
              <span className="stage__status">{stateLabel(stage.status)}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </li>
  )
}

function processingHint(
  status: JobStatusResponse | null,
  filename: string | null,
  stage: string | null,
): string {
  if (!status) {
    return 'Creating the job and sending the documents.'
  }
  if (filename && stage) {
    return `${filename} · ${stage}`
  }
  if (status.documents_completed === status.documents_total) {
    return 'Collecting the decisions.'
  }
  return 'Waiting for the next document to start.'
}
