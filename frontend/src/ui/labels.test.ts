import { describe, expect, it } from 'vitest'
import { CHECK_STATUS_LABELS, DECISION_LABELS } from './labels'

describe('DECISION_LABELS', () => {
  it('uses the agreed decision wording', () => {
    expect(DECISION_LABELS).toEqual({
      approve: 'Approve',
      reject: 'Reject',
      needs_person: 'Needs a person to check',
    })
  })
})

describe('CHECK_STATUS_LABELS', () => {
  it('maps check statuses to Pass, Warning and Fail', () => {
    expect(CHECK_STATUS_LABELS).toEqual({
      pass: 'Pass',
      needs_person: 'Warning',
      reject: 'Fail',
    })
  })
})
