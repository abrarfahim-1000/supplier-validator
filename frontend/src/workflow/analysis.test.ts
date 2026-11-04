import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/client'
import type { JobStatusResponse } from '@/api/client'
import { AnalysisError, POLL_INTERVAL_MS, runAnalysis } from './analysis'

const purchaseRequest = new File(['item_code'], 'request.csv', { type: 'text/csv' })
const supplierQuote = new File(['%PDF-'], 'quote.pdf', { type: 'application/pdf' })

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function statusPayload(
  state: JobStatusResponse['state'],
  overrides: Partial<JobStatusResponse> = {},
): JobStatusResponse {
  return {
    id: 'job-1',
    state,
    documents_total: 2,
    documents_completed: state === 'completed' ? 2 : 1,
    created_at: '2026-11-04T00:00:00Z',
    updated_at: '2026-11-04T00:00:01Z',
    documents: [],
    ...overrides,
  }
}

/** First response answers `POST /jobs`; the rest answer status polls in order. */
function stubFetchSequence(responses: Array<Response | Error>) {
  const fetchMock = vi.fn(async () => {
    const next = responses.shift()
    if (next === undefined) {
      throw new Error('Unexpected fetch call')
    }
    if (next instanceof Error) {
      throw next
    }
    return next
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function createdJob(): Response {
  return jsonResponse(
    { id: 'job-1', state: 'queued', documents_total: 2, created_at: '2026-11-04T00:00:00Z' },
    201,
  )
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('runAnalysis', () => {
  it('polls until the job is completed and reports every status', async () => {
    vi.useFakeTimers()
    stubFetchSequence([
      createdJob(),
      jsonResponse(statusPayload('queued')),
      jsonResponse(statusPayload('processing')),
      jsonResponse(statusPayload('completed')),
    ])

    const seen: string[] = []
    const done = runAnalysis({
      purchaseRequest,
      supplierQuotes: [supplierQuote],
      onStatus: (status) => seen.push(status.state),
    })

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)

    await expect(done).resolves.toMatchObject({ state: 'completed', documents_completed: 2 })
    expect(seen).toEqual(['queued', 'processing', 'completed'])
  })

  it('fails with the job error when the backend reports a failed job', async () => {
    vi.useFakeTimers()
    stubFetchSequence([
      createdJob(),
      jsonResponse(statusPayload('processing')),
      jsonResponse(
        statusPayload('failed', {
          error: { code: 'llm_unavailable', message: 'The language model is unavailable.' },
        }),
      ),
    ])

    const outcome = runAnalysis({
      purchaseRequest,
      supplierQuotes: [supplierQuote],
    }).then(
      () => null,
      (error: unknown) => error,
    )

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2)

    const error = await outcome
    expect(error).toBeInstanceOf(AnalysisError)
    expect(error).toMatchObject({
      code: 'llm_unavailable',
      message: 'The language model is unavailable.',
    })
  })

  it('retries a dropped connection and resumes polling', async () => {
    vi.useFakeTimers()
    const fetchMock = stubFetchSequence([
      createdJob(),
      new TypeError('Failed to fetch'),
      jsonResponse(statusPayload('processing')),
      jsonResponse(statusPayload('completed')),
    ])

    const done = runAnalysis({ purchaseRequest, supplierQuotes: [supplierQuote] })

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)

    await expect(done).resolves.toMatchObject({ state: 'completed' })
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })

  it('gives up after the retry budget on a persistent connection failure', async () => {
    vi.useFakeTimers()
    stubFetchSequence([
      createdJob(),
      new TypeError('Failed to fetch'),
      new TypeError('Failed to fetch'),
      new TypeError('Failed to fetch'),
      new TypeError('Failed to fetch'),
    ])

    const outcome = runAnalysis({ purchaseRequest, supplierQuotes: [supplierQuote] }).then(
      () => null,
      (error: unknown) => error,
    )

    await vi.advanceTimersByTimeAsync(7000)

    const error = await outcome
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'network_error' })
  })

  it('stops polling when the run is aborted', async () => {
    vi.useFakeTimers()
    stubFetchSequence([createdJob(), jsonResponse(statusPayload('processing'))])

    const controller = new AbortController()
    const outcome = runAnalysis({
      purchaseRequest,
      supplierQuotes: [supplierQuote],
      signal: controller.signal,
    }).then(
      () => null,
      (error: unknown) => error,
    )

    await vi.advanceTimersByTimeAsync(0)
    controller.abort()

    const error = await outcome
    expect((error as Error).name).toBe('AbortError')
  })

  it('does not start a job when the signal is already aborted', async () => {
    const fetchMock = stubFetchSequence([])
    const controller = new AbortController()
    controller.abort()

    const outcome = runAnalysis({
      purchaseRequest,
      supplierQuotes: [supplierQuote],
      signal: controller.signal,
    }).then(
      () => null,
      (error: unknown) => error,
    )

    const error = await outcome
    expect((error as Error).name).toBe('AbortError')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
