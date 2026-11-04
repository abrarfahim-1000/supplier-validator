import { ApiError, createJob, getJobStatus } from '@/api/client'
import type { JobStatusResponse } from '@/api/client'

/** The backend contract asks for a cheap status request about once per second. */
export const POLL_INTERVAL_MS = 1000

/**
 * A dropped connection is retried before the run is failed, so a short network blip does
 * not throw away a job that is still running on the server.
 */
const TRANSIENT_RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 15000] as const

/** The job reached a terminal state other than `completed`. */
export class AnalysisError extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'AnalysisError'
    this.code = code
  }
}

export interface RunAnalysisInput {
  purchaseRequest: File
  supplierQuotes: readonly File[]
  signal?: AbortSignal
  /** Called after every accepted status poll, so the UI can show real progress. */
  onStatus?: (status: JobStatusResponse) => void
  /** Stays interrupted while the same job id is retried after a network failure. */
  onConnectionInterrupted?: (interrupted: boolean) => void
  pollIntervalMs?: number
}

/** Creates the job, then polls until it is completed or failed. */
export async function runAnalysis(input: RunAnalysisInput): Promise<JobStatusResponse> {
  const { signal, onStatus, pollIntervalMs = POLL_INTERVAL_MS } = input
  signal?.throwIfAborted()

  const job = await createJob({
    purchaseRequest: input.purchaseRequest,
    supplierQuotes: input.supplierQuotes,
  })

  return waitForJob(job.id, {
    signal,
    onStatus,
    onConnectionInterrupted: input.onConnectionInterrupted,
    pollIntervalMs,
  })
}

interface WaitForJobOptions {
  signal?: AbortSignal
  onStatus?: (status: JobStatusResponse) => void
  onConnectionInterrupted?: (interrupted: boolean) => void
  pollIntervalMs: number
}

async function waitForJob(
  jobId: string,
  { signal, onStatus, onConnectionInterrupted, pollIntervalMs }: WaitForJobOptions,
): Promise<JobStatusResponse> {
  let transientFailures = 0

  for (;;) {
    signal?.throwIfAborted()

    let status: JobStatusResponse
    try {
      status = await getJobStatus(jobId, signal)
      transientFailures = 0
      onConnectionInterrupted?.(false)
    } catch (error) {
      if (!isTransient(error)) {
        throw error
      }
      const retryDelay = TRANSIENT_RETRY_DELAYS_MS[
        Math.min(transientFailures, TRANSIENT_RETRY_DELAYS_MS.length - 1)
      ] ?? 15000
      transientFailures += 1
      onConnectionInterrupted?.(true)
      await pause(retryDelay, signal)
      continue
    }

    onStatus?.(status)

    if (status.state === 'completed') {
      return status
    }

    if (status.state === 'failed') {
      throw new AnalysisError(
        status.error?.code ?? 'job_failed',
        status.error?.message ?? 'The validation service could not finish this job.',
      )
    }

    await pause(pollIntervalMs, signal)
  }
}

/** Retry a result fetch without losing the completed job id or the user's progress state. */
export async function getResultsWithRetry<T>(
  fetchResults: () => Promise<T>,
  options: { signal?: AbortSignal; onConnectionInterrupted?: (interrupted: boolean) => void },
): Promise<T> {
  const { signal, onConnectionInterrupted } = options
  let transientFailures = 0

  for (;;) {
    signal?.throwIfAborted()
    try {
      const result = await fetchResults()
      onConnectionInterrupted?.(false)
      return result
    } catch (error) {
      if (!isTransient(error)) {
        throw error
      }
      const retryDelay = TRANSIENT_RETRY_DELAYS_MS[
        Math.min(transientFailures, TRANSIENT_RETRY_DELAYS_MS.length - 1)
      ] ?? 15000
      transientFailures += 1
      onConnectionInterrupted?.(true)
      await pause(retryDelay, signal)
    }
  }
}

function isTransient(error: unknown): boolean {
  return error instanceof ApiError && (error.code === 'network_error' || error.status >= 500)
}

function pause(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted === true) {
    return Promise.reject(new DOMException('The run was aborted.', 'AbortError'))
  }

  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)

    const onAbort = () => {
      clearTimeout(timer)
      reject(new DOMException('The run was aborted.', 'AbortError'))
    }

    signal?.addEventListener('abort', onAbort, { once: true })
  })
}
