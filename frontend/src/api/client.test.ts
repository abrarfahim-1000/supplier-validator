import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createJob, getHealth, getJobStatus } from './client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubFetch(
  handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
) {
  const fetchMock = vi.fn(handler)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('getHealth', () => {
  it('returns the parsed health payload', async () => {
    const payload = { status: 'ok', version: '0.1.0' }
    const fetchMock = stubFetch(async () => jsonResponse(payload))

    await expect(getHealth()).resolves.toEqual(payload)
    expect(String(fetchMock.mock.calls[0]?.[0])).toMatch(/\/health$/)
  })
})

describe('getJobStatus', () => {
  it('parses the polling payload and encodes the job id', async () => {
    const payload = {
      id: 'job 1',
      state: 'processing',
      documents_total: 1,
      documents_completed: 0,
      created_at: '2026-11-04T00:00:00Z',
      updated_at: '2026-11-04T00:00:01Z',
      documents: [],
    }
    const fetchMock = stubFetch(async () => jsonResponse(payload))

    await expect(getJobStatus('job 1')).resolves.toEqual(payload)
    expect(String(fetchMock.mock.calls[0]?.[0])).toMatch(/\/jobs\/job%201$/)
  })

  it('turns the backend error envelope into an ApiError', async () => {
    stubFetch(async () =>
      jsonResponse(
        { error: { code: 'job_not_found', message: 'No job with that id.' } },
        404,
      ),
    )

    const caught: unknown = await getJobStatus('gone').catch((error: unknown) => error)

    expect(caught).toBeInstanceOf(ApiError)
    expect(caught).toMatchObject({
      code: 'job_not_found',
      message: 'No job with that id.',
      status: 404,
    })
  })

  it('falls back to a stable code when the error body is not JSON', async () => {
    stubFetch(async () => new Response('Bad gateway', { status: 502 }))

    const caught: unknown = await getJobStatus('job-1').catch((error: unknown) => error)

    expect(caught).toMatchObject({ code: 'http_error', status: 502 })
  })

  it('reports a transport failure as a network error', async () => {
    stubFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    const caught: unknown = await getJobStatus('job-1').catch((error: unknown) => error)

    expect(caught).toMatchObject({ code: 'network_error', status: 0 })
  })
})

describe('createJob', () => {
  it('sends one CSV and every PDF as multipart fields', async () => {
    const purchaseRequest = new File(['item_code'], 'request.csv', {
      type: 'text/csv',
    })
    const quoteA = new File(['%PDF-'], 'a.pdf', { type: 'application/pdf' })
    const quoteB = new File(['%PDF-'], 'b.pdf', { type: 'application/pdf' })
    const fetchMock = stubFetch(async () =>
      jsonResponse(
        {
          id: 'job-1',
          state: 'queued',
          documents_total: 2,
          created_at: '2026-11-04T00:00:00Z',
        },
        201,
      ),
    )

    await createJob({ purchaseRequest, supplierQuotes: [quoteA, quoteB] })

    const init = fetchMock.mock.calls[0]?.[1]
    expect(init?.method).toBe('POST')
    expect(init?.body).toBeInstanceOf(FormData)

    const body = init?.body
    if (!(body instanceof FormData)) {
      throw new Error('createJob did not send a FormData body')
    }

    expect((body.get('purchase_request') as File).name).toBe('request.csv')
    expect(body.getAll('supplier_quotes')).toHaveLength(2)
  })
})
