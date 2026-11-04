import { IconFile, IconFileTypePdf, IconX } from '@tabler/icons-react'
import type { FileRejection } from 'react-dropzone'
import { DropZone } from './drop-zone'
import type { ServiceState } from '@/workflow/health'
import { MAX_QUOTATIONS } from '@/workflow/limits'

const MAX_PDF_BYTES = 5 * 1024 * 1024

export interface UploadStageProps {
  purchaseRequest: File | null
  quotations: readonly File[]
  service: ServiceState
  error: string | null
  onPurchaseRequest: (file: File | null) => void
  onQuotations: (files: File[]) => void
  onRemoveQuotation: (index: number) => void
  onReject: (message: string) => void
  onRun: () => void
}

function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  const kilobytes = bytes / 1024
  return kilobytes < 1024
    ? `${Math.round(kilobytes)} KB`
    : `${(kilobytes / 1024).toFixed(1)} MB`
}

function describeRejections(rejections: FileRejection[]): string {
  return rejections
    .map(({ file, errors }) => `${file.name}: ${errors.map((error) => error.message).join(', ')}`)
    .join(' ')
}

export function UploadStage({
  purchaseRequest,
  quotations,
  service,
  error,
  onPurchaseRequest,
  onQuotations,
  onRemoveQuotation,
  onReject,
  onRun,
}: UploadStageProps) {
  const canRun = purchaseRequest !== null && quotations.length > 0 && service === 'ready'

  return (
    <>
      <section className="intro">
        <h1>Check supplier quotations against the purchase request.</h1>
        <p className="intro__lede">
          Upload the company request and 1–20 supplier quotations. Every decision names
          the rule behind it and quotes the line it was read from. Anything the checker cannot
          verify goes to a person.
        </p>
      </section>

      <div className="upload">
        <div className="upload__fields">
          <section>
            <div className="section__head">
              <h2 className="section__title">Purchase request</h2>
              <p className="section__note">
                {purchaseRequest ? '1 purchase request selected' : '1 CSV or JSON required'}
              </p>
            </div>
            <p className="section__hint">
              The company request every quotation is checked against.
            </p>

            <DropZone
              icon={<IconFile size={22} stroke={1.4} />}
              primary={
                purchaseRequest
                  ? 'Replace the purchase request file'
                  : 'Drop the purchase request file'
              }
              secondary="or browse for the file · one CSV or JSON"
              onFiles={(files) => {
                void validatePurchaseRequestFile(files[0]).then((file) => {
                  if (file) onPurchaseRequest(file)
                  else onReject(`${files[0]?.name ?? 'File'}: choose a valid CSV or purchase request JSON file.`)
                })
              }}
              onReject={(rejections) => onReject(describeRejections(rejections))}
            />

            {purchaseRequest ? (
              <ul className="file-list">
                <FileRow
                  file={purchaseRequest}
                  kind="PR"
                  onRemove={() => onPurchaseRequest(null)}
                />
              </ul>
            ) : null}
          </section>

          <section>
            <div className="section__head">
              <h2 className="section__title">Supplier quotations</h2>
              <p className="section__note">
                {quotations.length} of {MAX_QUOTATIONS}
              </p>
            </div>
            <p className="section__hint">Upload 1–20 supplier quotation PDFs.</p>

            <DropZone
              multiple
              maxFiles={MAX_QUOTATIONS}
              maxSize={MAX_PDF_BYTES}
              icon={<IconFileTypePdf size={22} stroke={1.4} />}
              primary="Drop supplier quotations"
              secondary="or browse for PDFs · up to 20 files, 5 MB each"
              onFiles={(files) => {
                void Promise.all(files.map(validatePdfFile)).then((validity) => {
                  const validFiles = files.filter((_, index) => validity[index])
                  const invalidFiles = files.filter((_, index) => !validity[index])
                  if (validFiles.length > 0) onQuotations(validFiles)
                  if (invalidFiles.length > 0) {
                    onReject(`${invalidFiles.map((file) => file.name).join(', ')}: file content is not a PDF.`)
                  }
                })
              }}
              onReject={(rejections) => onReject(describeRejections(rejections))}
            />

            {quotations.length > 0 ? (
              <ul className="file-list">
                {quotations.map((file, index) => (
                  <FileRow
                    key={`${file.name}-${file.size}-${index}`}
                    file={file}
                    kind="PDF"
                    onRemove={() => onRemoveQuotation(index)}
                  />
                ))}
              </ul>
            ) : null}
          </section>
        </div>

        <aside className="rail" aria-label="Run the validation">
          <p className="rail__state">{railState(service)}</p>

          <div className="rail__counts">
            <div className="rail__count" data-empty={purchaseRequest === null}>
              <span>Purchase request</span>
              <b>{purchaseRequest ? '1 PR' : 'None'}</b>
            </div>
            <div className="rail__count" data-empty={quotations.length === 0}>
              <span>Supplier quotations</span>
              <b>
                {quotations.length} / {MAX_QUOTATIONS}
              </b>
            </div>
          </div>

          <button
            type="button"
            className="button button--block"
            onClick={onRun}
            disabled={!canRun}
            aria-busy={false}
          >
            Run validation
          </button>

          <p className="rail__note">
            {railNote(service, purchaseRequest, quotations.length)}
          </p>

          {error ? (
            <div className="notice" role="alert">
              <span className="notice__label">Could not run</span>
              {error}
            </div>
          ) : null}
        </aside>
      </div>
    </>
  )
}

function railState(service: ServiceState): string {
  if (service === 'ready') {
    return 'Ready to run'
  }
  return service === 'starting' ? 'Waking the service' : 'Service unreachable'
}

function railNote(
  service: ServiceState,
  purchaseRequest: File | null,
  quotationCount: number,
): string {
  if (service === 'starting') {
    return 'The first request after a pause can take a minute. The button unlocks when the service answers.'
  }
  if (service === 'down') {
    return 'The validation service is not answering. Retry from the header, then run again.'
  }
  if (!purchaseRequest && quotationCount === 0) {
    return 'Add the purchase request (CSV or JSON) and at least one supplier quotation to run.'
  }
  if (!purchaseRequest) {
    return 'Add the purchase request (CSV or JSON) to run.'
  }
  if (quotationCount === 0) {
    return 'Add at least one supplier quotation to run.'
  }
  return 'Documents are checked one at a time, about 15–20 seconds each. Nothing is skipped and nothing is guessed.'
}

function FileRow({
  file,
  kind,
  onRemove,
}: {
  file: File
  kind: 'PR' | 'PDF'
  onRemove: () => void
}) {
  return (
    <li className="file-row">
      <span className="file-row__type">{kind}</span>
      <span className="file-row__name" title={file.name}>
        {file.name}
      </span>
      <span className="file-row__size">{formatSize(file.size)}</span>
      <button
        type="button"
        className="file-row__remove"
        onClick={onRemove}
        aria-label={`Remove ${file.name}`}
      >
        <IconX size={15} stroke={1.6} aria-hidden="true" />
      </button>
    </li>
  )
}

async function validatePdfFile(file: File): Promise<boolean> {
  const header = new Uint8Array(await file.slice(0, 5).arrayBuffer())
  return new TextDecoder().decode(header) === '%PDF-'
}

async function validatePurchaseRequestFile(file: File | undefined): Promise<File | null> {
  if (!file) return null
  try {
    const text = await file.text()
    const firstCharacter = text.replace(/^\uFEFF/, '').trimStart()[0]
    if (firstCharacter === '{') {
      const value: unknown = JSON.parse(text)
      if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
      const request = value as { pr_number?: unknown; lines?: unknown }
      if (typeof request.pr_number !== 'string' || !Array.isArray(request.lines)) return null
      return file
    }
    if (firstCharacter === '[') return null
    const headers = (text.split(/\r?\n/, 1)[0] ?? '').split(',').map((header) => header.trim())
    const required = [
      'PR number',
      'Item',
      'Description',
      'Unit',
      'Quantity requested',
      'Maximum unit price (BDT)',
    ]
    return required.every((header) => headers.includes(header)) ? file : null
  } catch {
    return null
  }
}
