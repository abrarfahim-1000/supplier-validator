import { describe, expect, it } from 'vitest'
import type { DocumentResult } from '@/api/client'
import type { components } from '@/api/schema'
import {
  decisionShare,
  displayField,
  formatPercent,
  headline,
  splitChecks,
  summarizeDecisions,
} from './result-view'

type CheckResult = components['schemas']['CheckResult']

function check(code: string, status: CheckResult['status']): CheckResult {
  return { code, status, rule_id: code, title: code, detail: `${code} detail` }
}

function result(overrides: Partial<DocumentResult> = {}): DocumentResult {
  return {
    document_id: 'doc-01',
    source_filename: 'quote.pdf',
    decision: 'approve',
    reasons: [],
    checks: [],
    processing_failure: false,
    ...overrides,
  }
}

describe('summarizeDecisions', () => {
  it('counts each decision category separately', () => {
    const summary = summarizeDecisions([
      result({ document_id: 'a', decision: 'approve' }),
      result({ document_id: 'b', decision: 'reject' }),
      result({ document_id: 'c', decision: 'needs_person' }),
      result({ document_id: 'd', decision: 'needs_person' }),
    ])

    expect(summary).toEqual({ approve: 1, reject: 1, needsPerson: 2 })
  })
})

describe('headline', () => {
  it('uses the processing failure detail when the document failed', () => {
    expect(
      headline(
        result({
          decision: 'needs_person',
          processing_failure: true,
          failure_detail: 'The PDF is scanned.',
        }),
      ),
    ).toBe('The PDF is scanned.')
  })

  it('uses the first backend reason when there is one', () => {
    expect(
      headline(
        result({
          decision: 'reject',
          reasons: [
            {
              code: 'REJ-01',
              rule_id: 'REJ-01',
              title: 'Price above maximum',
              detail: 'quoted unit price is 6.0% above the maximum',
            },
          ],
        }),
      ),
    ).toBe('quoted unit price is 6.0% above the maximum')
  })

  it('does not invent a reason for an approval without reasons', () => {
    expect(headline(result())).toBe('All company rules passed.')
  })
})

describe('displayField', () => {
  it('shows the extracted value as written', () => {
    expect(displayField({ value: '45', status: 'ok' })).toEqual({ text: '45', flagged: false })
  })

  it('flags a missing field instead of filling it in', () => {
    expect(displayField({ value: null, status: 'missing' })).toEqual({
      text: 'Not found',
      flagged: true,
    })
  })

  it('keeps the note for an ambiguous value', () => {
    expect(displayField({ value: '30 to 90 days', status: 'ambiguous', note: 'range' })).toEqual({
      text: '30 to 90 days (range)',
      flagged: true,
    })
  })
})

describe('formatPercent', () => {
  it('rounds to one decimal for display', () => {
    expect(formatPercent('-1.666666666666666666666666667')).toBe('-1.7%')
  })

  it('leaves an unparseable value untouched', () => {
    expect(formatPercent('as agreed')).toBe('as agreed')
  })

  it('rounds on the decimal string, not through a float', () => {
    expect(formatPercent('0.05')).toBe('0.1%')
    expect(formatPercent('9.99')).toBe('10.0%')
  })

  it('never prints a negative zero', () => {
    expect(formatPercent('-0.04')).toBe('0.0%')
  })
})

describe('splitChecks', () => {
  it('puts rejections before warnings and keeps passing checks separate', () => {
    const { flagged, passed } = splitChecks([
      check('NP-01', 'needs_person'),
      check('REJ-01', 'reject'),
      check('REJ-02', 'pass'),
      check('REJ-03', 'reject'),
    ])

    expect(flagged.map((item) => item.code)).toEqual(['REJ-01', 'REJ-03', 'NP-01'])
    expect(passed.map((item) => item.code)).toEqual(['REJ-02'])
  })

  it('keeps every passing check available for the collapsed list', () => {
    const { flagged, passed } = splitChecks([check('A', 'pass'), check('B', 'pass')])
    expect(flagged).toEqual([])
    expect(passed).toHaveLength(2)
  })
})

describe('decisionShare', () => {
  it('omits categories that did not occur', () => {
    const share = decisionShare({ approve: 2, reject: 0, needsPerson: 1 })
    expect(share.map((part) => part.decision)).toEqual(['approve', 'needs_person'])
    expect(share.reduce((total, part) => total + part.percent, 0)).toBeCloseTo(100)
  })

  it('has no bar to draw for an empty result set', () => {
    expect(decisionShare({ approve: 0, reject: 0, needsPerson: 0 })).toEqual([])
  })
})
