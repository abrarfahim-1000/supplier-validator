import type { components } from './schema'

export type HealthResponse = components['schemas']['HealthResponse']
export type JobCreatedResponse = components['schemas']['JobCreatedResponse']
export type JobStatusResponse = components['schemas']['JobStatusResponse']
export type JobResultsResponse = components['schemas']['JobResultsResponse']
export type DocumentResult = components['schemas']['DocumentResult']
export type DocumentStatusPayload = components['schemas']['DocumentStatusPayload']
export type ErrorResponse = components['schemas']['ErrorResponse']

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL ?? ''

/** Public API origin. Empty means the app is served from the same origin as the API. */
export const API_BASE_URL = configuredBaseUrl.replace(/\/+$/, '')

/**
 * Every failure reaches the UI as one of these. `code` is the backend's stable error code,
 * or a frontend-only code for transport and malformed-response failures.
 */
export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init)
  } catch {
    throw new ApiError(
      'network_error',
      'Could not reach the validation service. Check the connection and try again.',
      0,
    )
  }

  if (!response.ok) {
    throw await errorFromResponse(response)
  }

  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError(
      'invalid_response',
      'The validation service returned an unreadable response.',
      response.status,
    )
  }
}

/** Turns the backend's `{error: {code, message}}` envelope into an `ApiError`. */
export async function errorFromResponse(response: Response): Promise<ApiError> {
  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    // A proxy or an unexpected failure can answer without JSON.
  }

  if (isErrorResponse(payload)) {
    return new ApiError(payload.error.code, payload.error.message, response.status)
  }

  return new ApiError(
    'http_error',
    `The validation service could not complete the request (status ${response.status}).`,
    response.status,
  )
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  if (typeof value !== 'object' || value === null) {
    return false
  }
  const error = (value as { error?: unknown }).error
  if (typeof error !== 'object' || error === null) {
    return false
  }
  const { code, message } = error as { code?: unknown; message?: unknown }
  return typeof code === 'string' && typeof message === 'string'
}

/** Wake the backend and confirm it is reachable. */
export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health')
}

export interface CreateJobInput {
  purchaseRequest: File
  supplierQuotes: readonly File[]
}

/** Creates the job and returns immediately; processing continues on the server. */
export function createJob(input: CreateJobInput): Promise<JobCreatedResponse> {
  const body = new FormData()
  body.append('purchase_request', input.purchaseRequest, input.purchaseRequest.name)
  for (const file of input.supplierQuotes) {
    body.append('supplier_quotes', file, file.name)
  }

  return request<JobCreatedResponse>('/jobs', { method: 'POST', body })
}

/** Small polling payload: counts and per-document stage statuses, never results. */
export function getJobStatus(jobId: string, signal?: AbortSignal): Promise<JobStatusResponse> {
  return request<JobStatusResponse>(`/jobs/${encodeURIComponent(jobId)}`, { signal })
}

/** Only available once the job reports `completed`; `409` before that. */
export function getJobResults(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobResultsResponse> {
  return request<JobResultsResponse>(`/jobs/${encodeURIComponent(jobId)}/results`, { signal })
}
