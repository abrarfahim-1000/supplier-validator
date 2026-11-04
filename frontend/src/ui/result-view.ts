import type { DocumentResult } from '@/api/client'
import type { components } from '@/api/schema'
import type { CheckStatus, Decision } from './labels'

type CheckResult = components['schemas']['CheckResult']

export interface DecisionCounts {
  approve: number
  reject: number
  needsPerson: number
}

/** Counts every document exactly once; the dashboard header uses these totals. */
export function summarizeDecisions(results: readonly DocumentResult[]): DecisionCounts {
  return results.reduce<DecisionCounts>(
    (counts, result) => {
      if (result.decision === 'approve') {
        counts.approve += 1
      } else if (result.decision === 'reject') {
        counts.reject += 1
      } else {
        counts.needsPerson += 1
      }
      return counts
    },
    { approve: 0, reject: 0, needsPerson: 0 },
  )
}

export interface DecisionShare {
  decision: Decision
  count: number
  /** Exact proportion, for the summary bar. Never used as a number in text. */
  percent: number
}

/** Only categories that occur are returned, so the bar has no empty segments. */
export function decisionShare(counts: DecisionCounts): DecisionShare[] {
  const total = counts.approve + counts.reject + counts.needsPerson
  if (total === 0) {
    return []
  }

  const parts: DecisionShare[] = [
    { decision: 'approve', count: counts.approve, percent: (counts.approve / total) * 100 },
    { decision: 'reject', count: counts.reject, percent: (counts.reject / total) * 100 },
    {
      decision: 'needs_person',
      count: counts.needsPerson,
      percent: (counts.needsPerson / total) * 100,
    },
  ]

  return parts.filter((part) => part.count > 0)
}

const CHECK_ORDER: Record<CheckStatus, number> = {
  reject: 0,
  needs_person: 1,
  pass: 2,
}

/** Triggered checks first, rejections before warnings; passing checks are kept for reference. */
export function splitChecks(checks: readonly CheckResult[]): {
  flagged: CheckResult[]
  passed: CheckResult[]
} {
  const flagged = checks
    .filter((check) => check.status !== 'pass')
    .sort((left, right) => CHECK_ORDER[left.status] - CHECK_ORDER[right.status])
  const passed = checks.filter((check) => check.status === 'pass')
  return { flagged, passed }
}

/** One line for the collapsed card, taken from the backend, never inferred here. */
export function headline(result: DocumentResult): string {
  if (result.processing_failure) {
    return result.failure_detail ?? 'Processing failed before a decision could be made.'
  }

  const firstReason = result.reasons[0]
  if (firstReason) {
    return firstReason.detail
  }

  return result.decision === 'approve'
    ? 'All company rules passed.'
    : 'No reason was returned for this decision.'
}

export interface DisplayField {
  text: string
  /** True when the backend could not use the value as written. */
  flagged: boolean
}

interface FieldLike {
  value?: unknown
  status: string
  note?: string | null
}

/** Shows exactly what the backend extracted, never a guessed replacement. */
export function displayField(field: FieldLike | null | undefined): DisplayField {
  if (!field) {
    return { text: 'Not found', flagged: true }
  }

  const flagged = field.status !== 'ok'
  const { value } = field
  if (value === null || value === undefined || value === '') {
    return { text: field.note ?? 'Not found', flagged: true }
  }

  const text = String(value)
  return {
    text: flagged && field.note ? `${text} (${field.note})` : text,
    flagged,
  }
}

/**
 * Percentages are rounded to one decimal for display only. The rounding is done on the
 * decimal string the backend sent, so no binary float ever touches a money or percentage
 * value.
 */
export function formatPercent(value: string): string {
  const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(value.trim())
  if (!match) {
    return value
  }

  const [, sign, whole, fraction = ''] = match
  const firstDecimal = fraction[0] ?? '0'
  const roundUp = Number(fraction[1] ?? '0') >= 5
  const scaled = Number(`${whole}${firstDecimal}`) + (roundUp ? 1 : 0)
  const digits = String(scaled).padStart(2, '0')
  const rounded = `${digits.slice(0, -1)}.${digits.slice(-1)}`
  const negative = sign === '-' && scaled !== 0

  return `${negative ? '-' : ''}${rounded}%`
}
