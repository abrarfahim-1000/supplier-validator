import type { components } from '../api/schema'

export type Decision = components['schemas']['Decision']
export type CheckStatus = components['schemas']['CheckStatus']

/** Exact display labels agreed for the three decisions. */
export const DECISION_LABELS: Record<Decision, string> = {
  approve: 'Approve',
  reject: 'Reject',
  needs_person: 'Needs a person to check',
}

/** Exact display labels for per-rule check statuses. */
export const CHECK_STATUS_LABELS: Record<CheckStatus, string> = {
  pass: 'Pass',
  needs_person: 'Warning',
  reject: 'Fail',
}
