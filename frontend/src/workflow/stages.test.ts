import { describe, expect, it } from 'vitest'
import { PROCESSING_STAGES } from './stages'

describe('PROCESSING_STAGES', () => {
  it('lists the five backend stages in pipeline order', () => {
    expect(PROCESSING_STAGES).toEqual([
      'Document Ingestion',
      'Information Extraction',
      'Purchase Request Comparison',
      'Company Rule Validation',
      'Decision Generation',
    ])
  })
})
