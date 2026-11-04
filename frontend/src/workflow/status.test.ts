import { describe, expect, it } from 'vitest'
import type { JobStatusResponse } from '@/api/client'
import {
  activeDocument,
  currentStageName,
  progressPercent,
  showsStages,
  stateLabel,
} from './status'

const STAGE_NAMES = [
  'Document Ingestion',
  'Information Extraction',
  'Purchase Request Comparison',
  'Company Rule Validation',
  'Decision Generation',
]

function document(
  id: string,
  state: 'pending' | 'processing' | 'completed' | 'failed',
  processingStage?: string,
) {
  return {
    id,
    filename: `${id}.pdf`,
    state,
    stages: STAGE_NAMES.map((name) => ({
      name,
      status:
        processingStage === name
          ? ('processing' as const)
          : state === 'completed'
            ? ('completed' as const)
            : ('pending' as const),
    })),
  }
}

function status(overrides: Partial<JobStatusResponse> = {}): JobStatusResponse {
  return {
    id: 'job-1',
    state: 'processing',
    created_at: '2026-11-04T00:00:00Z',
    updated_at: '2026-11-04T00:00:00Z',
    documents_total: 4,
    documents_completed: 1,
    documents: [document('a', 'completed'), document('b', 'processing', 'Information Extraction')],
    ...overrides,
  }
}

describe('progressPercent', () => {
  it('is zero before the first status arrives', () => {
    expect(progressPercent(null)).toBe(0)
  })

  it('tracks finished documents', () => {
    expect(progressPercent(status())).toBe(25)
  })

  it('never exceeds a full bar', () => {
    expect(progressPercent(status({ documents_completed: 5 }))).toBe(100)
  })
})

describe('activeDocument', () => {
  it('prefers the document the pipeline is on', () => {
    expect(activeDocument(status())?.id).toBe('b')
  })

  it('falls back to the next waiting document', () => {
    const payload = status({
      documents: [document('a', 'completed'), document('b', 'pending')],
    })
    expect(activeDocument(payload)?.id).toBe('b')
  })

  it('returns nothing once every document is finished', () => {
    const payload = status({ documents: [document('a', 'completed')] })
    expect(activeDocument(payload)).toBeNull()
  })
})

describe('currentStageName', () => {
  it('names the stage the backend reports as processing', () => {
    const active = activeDocument(status())
    expect(currentStageName(active)).toBe('Information Extraction')
  })
})

describe('showsStages', () => {
  it('expands stages for running and failed documents only', () => {
    expect(showsStages(document('a', 'processing', 'Document Ingestion'))).toBe(true)
    expect(showsStages(document('b', 'failed'))).toBe(true)
    expect(showsStages(document('c', 'pending'))).toBe(false)
    expect(showsStages(document('d', 'completed'))).toBe(false)
  })
})

describe('stateLabel', () => {
  it('uses one word per backend state', () => {
    expect(stateLabel('pending')).toBe('Pending')
    expect(stateLabel('processing')).toBe('Processing')
    expect(stateLabel('completed')).toBe('Completed')
    expect(stateLabel('failed')).toBe('Failed')
  })
})
