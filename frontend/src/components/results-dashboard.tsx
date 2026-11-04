import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { IconChevronDown } from '@tabler/icons-react'
import type { DocumentResult } from '@/api/client'
import type { components } from '@/api/schema'
import { CheckStatusLabel, Verdict } from './verdict'
import type { Decision } from '@/ui/labels'
import {
  decisionShare,
  displayField,
  formatPercent,
  headline,
  splitChecks,
  summarizeDecisions,
} from '@/ui/result-view'
import type { DisplayField } from '@/ui/result-view'

type CheckResult = components['schemas']['CheckResult']
type ComparisonIssue = components['schemas']['ComparisonIssue']
type Evidence = components['schemas']['Evidence']

const COMPARISON_ISSUES: Record<ComparisonIssue, string> = {
  none: 'The quotation matched one purchase request line.',
  no_match: 'No purchase request line matched this quotation.',
  ambiguous_match: 'More than one purchase request line matched this quotation.',
  unusable_values: 'The quoted values could not be compared with the purchase request.',
  multiple_line_items: 'The quotation has more than one line item.',
}

const MATCH_METHODS: Record<'item_code' | 'description', string> = {
  item_code: 'Matched by item code',
  description: 'Matched by description',
}

const SOURCE_LABELS: Record<Evidence['source'], string> = {
  supplier_document: 'Quotation',
  purchase_request: 'Purchase request',
}

const DECISION_SENTENCES: Record<Decision, string> = {
  approve: 'No company rule was triggered by this quotation.',
  reject: 'At least one company rule rejects this quotation.',
  needs_person: 'The rules cannot settle this quotation without a person reading it.',
}

const TALLY_LABELS: Record<Decision, string> = {
  approve: 'approved',
  reject: 'rejected',
  needs_person: 'needs a person',
}

export function ResultsDashboard({
  results,
  onRestart,
}: {
  results: readonly DocumentResult[]
  onRestart: () => void
}) {
  const counts = summarizeDecisions(results)
  const share = decisionShare(counts)

  return (
    <section className="results" aria-labelledby="results-heading">
      <header className="results__head">
        <div>
          <h1 id="results-heading" className="results__title">
            Results
          </h1>
          <p className="results__sub">
            {results.length} supplier {results.length === 1 ? 'quotation' : 'quotations'} checked
            against the purchase request
          </p>
        </div>
        <button type="button" className="button button--quiet" onClick={onRestart}>
          Check another batch
        </button>
      </header>

      <ul className="tally">
        {(Object.keys(TALLY_LABELS) as Decision[]).map((decision) => (
          <li key={decision} className="tally__item" data-tone={decision}>
            <span className="tally__count">
              {decision === 'needs_person' ? counts.needsPerson : counts[decision]}
            </span>
            <span className="tally__label">{TALLY_LABELS[decision]}</span>
          </li>
        ))}
      </ul>

      <div
        className="distribution"
        role="img"
        aria-label={share
          .map((part) => `${part.count} ${TALLY_LABELS[part.decision]}`)
          .join(', ')}
      >
        {share.map((part, index) => (
          <span
            key={part.decision}
            className="distribution__part"
            data-tone={part.decision}
            style={{ width: `${part.percent}%`, '--order': index } as CSSProperties}
          />
        ))}
      </div>

      {results.length > 0 ? (
        <div>
          {results.map((result) => (
            <ResultRow key={result.document_id} result={result} />
          ))}
        </div>
      ) : (
        <p className="results__sub">No supplier documents were returned for this job.</p>
      )}
    </section>
  )
}

function ResultRow({ result }: { result: DocumentResult }) {
  const [open, setOpen] = useState(false)
  const panelId = `result-panel-${result.document_id}`
  const title = result.supplier_name ?? result.source_filename
  const meta = result.quotation_number
    ? `Quote ${result.quotation_number} · ${result.source_filename}`
    : result.source_filename

  return (
    <article className="result" data-open={open}>
      <button
        type="button"
        className="result__toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="result__head">
          <span className="result__name">{title}</span>
          <span className="result__meta">{meta}</span>
        </span>
        <span className="result__side">
          <Verdict decision={result.decision} />
          <IconChevronDown
            size={16}
            stroke={1.6}
            aria-hidden="true"
            className="result__chevron"
          />
        </span>
        <span className="result__reason">{headline(result)}</span>
      </button>

      {open ? (
        <div id={panelId} className="result__panel">
          <DecisionPanel result={result} />
          <ExtractedPanel result={result} />
          <ComparisonPanel result={result} />
          <ChecksPanel checks={result.checks} />
        </div>
      ) : null}
    </article>
  )
}

function Panel({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="panel">
      <h3 className="panel__label">{label}</h3>
      <div className="panel__body">{children}</div>
    </section>
  )
}

function DecisionPanel({ result }: { result: DocumentResult }) {
  return (
    <Panel label="Decision">
      <div className="stack">
        <p>
          <Verdict decision={result.decision} />
        </p>

        {result.processing_failure ? (
          <p className="failure">
            {result.failure_detail ?? 'This document could not be processed.'}
          </p>
        ) : null}

        {result.reasons.length > 0 ? (
          <>
            <p className="panel__lead">{DECISION_SENTENCES[result.decision]}</p>
            <ol className="reasons">
              {result.reasons.map((reason) => (
                <li key={`${reason.code}-${reason.rule_id ?? 'none'}`} className="reason">
                  <span className="reason__id">{reason.rule_id ?? reason.code}</span>
                  <span>
                    <span className="reason__title">{reason.title}</span>
                    <span className="reason__detail">{reason.detail}</span>
                  </span>
                </li>
              ))}
            </ol>
          </>
        ) : result.processing_failure ? null : (
          <p className="panel__lead">{headline(result)}</p>
        )}
      </div>
    </Panel>
  )
}

function ExtractedPanel({ result }: { result: DocumentResult }) {
  const quote = result.quote

  return (
    <Panel label="Extracted">
      {!quote ? (
        <p className="panel__lead">No fields were extracted for this document.</p>
      ) : (
        <>
          <h4 className="subhead">Supplier</h4>
          <dl className="fields">
            <Field label="Supplier" field={displayField(quote.supplier_name)} />
            <Field label="Quotation number" field={displayField(quote.quotation_number)} />
            <Field label="Quote date" field={displayField(quote.quote_date)} />
            <Field
              label="Request reference"
              field={displayField(quote.purchase_request_reference)}
            />
            <Field label="TIN" field={displayField(quote.tin)} />
            <Field label="BIN" field={displayField(quote.bin)} />
          </dl>

          {quote.line_items.length > 0 ? (
            <>
              <h4 className="subhead">
                {quote.line_items.length === 1 ? 'Line item' : 'Line items'}
              </h4>
              <table className="items">
                <thead>
                  <tr>
                    <th scope="col">Description</th>
                    <th scope="col" className="num">
                      Quantity
                    </th>
                    <th scope="col" className="num">
                      Unit price
                    </th>
                    <th scope="col" className="num">
                      Line total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {quote.line_items.map((item, index) => {
                    const description = displayField(item.description)
                    const quantity = displayField(item.quantity)
                    const unitPrice = displayField(item.unit_price)
                    const lineTotal = displayField(item.line_total)
                    return (
                      <tr key={`${description.text}-${index}`}>
                        <td>
                          {description.text}
                          <span className="items__code">
                            {displayField(item.item_code).text} · {displayField(item.unit).text}
                          </span>
                        </td>
                        <td className="num" data-flagged={quantity.flagged}>
                          {quantity.text}
                        </td>
                        <td className="num" data-flagged={unitPrice.flagged}>
                          {unitPrice.text}
                        </td>
                        <td className="num" data-flagged={lineTotal.flagged}>
                          {lineTotal.text}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </>
          ) : null}

          <h4 className="subhead">Totals and VAT</h4>
          <dl className="fields">
            <Field label="Subtotal" field={displayField(quote.subtotal)} />
            <Field label="VAT rate" field={displayField(quote.vat_rate)} />
            <Field label="VAT amount" field={displayField(quote.vat_amount)} />
            <Field label="Total" field={displayField(quote.total)} />
            <Field label="VAT statement" field={displayField(quote.vat_statement)} />
          </dl>

          <h4 className="subhead">Terms</h4>
          <dl className="fields">
            <Field label="Payment days" field={displayField(quote.terms.payment_days)} />
            <Field
              label="Advance payment (%)"
              field={displayField(quote.terms.advance_percent)}
            />
            <Field label="Delivery days" field={displayField(quote.terms.delivery_days)} />
            <Field
              label="Validity (days)"
              field={displayField(quote.terms.validity_days)}
            />
            <Field
              label="Penalty per week (%)"
              field={displayField(quote.terms.penalty_percent_per_week)}
            />
            <Field
              label="Penalty basis"
              field={displayPenaltyBasis(quote.terms.penalty_basis_order_value.value)}
            />
            <Field
              label="Late-delivery penalty"
              field={displayField(quote.terms.late_penalty_clause)}
            />
          </dl>

          {result.flags && result.flags.length > 0 ? (
            <>
              <h4 className="subhead">Fields needing confirmation</h4>
              <ul className="checks">
                {result.flags.map((flag) => (
                  <li key={`${flag.field}-${flag.code}`} className="check" data-status="needs_person">
                    <span className="check__head">
                      <span className="check__rule">{flag.code}</span>
                      <span className="check__title">{flag.field}</span>
                    </span>
                    <p className="check__detail">{flag.detail}</p>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </>
      )}
    </Panel>
  )
}

function displayPenaltyBasis(value: boolean | null | undefined): DisplayField {
  if (value === true) {
    return { text: 'Yes, of order value', flagged: false }
  }
  if (value === false) {
    return { text: 'No', flagged: false }
  }
  return { text: 'Not found', flagged: true }
}

function Field({ label, field }: { label: string; field: DisplayField }) {
  return (
    <div>
      <dt className="field__term">{label}</dt>
      <dd className="field__value" data-flagged={field.flagged}>
        {field.text}
      </dd>
    </div>
  )
}

function ComparisonPanel({ result }: { result: DocumentResult }) {
  const comparison = result.comparison

  return (
    <Panel label="Purchase request">
      {!comparison ? (
        <p className="panel__lead">
          No purchase request comparison is available for this document.
        </p>
      ) : (
        <>
          <p className="panel__lead">{COMPARISON_ISSUES[comparison.issue]}</p>
          {comparison.detail ? <p className="panel__lead">{comparison.detail}</p> : null}

          {comparison.line ? (
            <>
              <table className="compare">
                <thead>
                  <tr>
                    <th scope="col" />
                    <th scope="col">Request line</th>
                    <th scope="col">Quotation</th>
                    <th scope="col">Difference</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">Quantity</th>
                    <td>{comparison.line.requested_quantity}</td>
                    <td>{comparison.line.quoted_quantity}</td>
                    <td>
                      {comparison.line.quantity_difference} (
                      {formatPercent(comparison.line.quantity_difference_percent)})
                    </td>
                  </tr>
                  <tr>
                    <th scope="row">Unit price (BDT)</th>
                    <td>{comparison.line.max_unit_price}</td>
                    <td>{comparison.line.quoted_unit_price}</td>
                    <td>
                      {comparison.line.unit_price_difference} (
                      {formatPercent(comparison.line.unit_price_difference_percent)})
                    </td>
                  </tr>
                </tbody>
              </table>

              <p className="section__hint">
                {MATCH_METHODS[comparison.line.matched_by]} ·{' '}
                {comparison.line.item_code} · {comparison.line.description}
              </p>

              <blockquote className="evidence">
                <span className="evidence__source">Purchase request line</span>
                <p className="evidence__text">{comparison.line.request_line_text}</p>
              </blockquote>
            </>
          ) : null}
        </>
      )}
    </Panel>
  )
}

function ChecksPanel({ checks }: { checks: readonly CheckResult[] }) {
  const { flagged, passed } = splitChecks(checks)

  return (
    <Panel label="Rule checks">
      {checks.length === 0 ? (
        <p className="panel__lead">No rule checks were returned for this document.</p>
      ) : flagged.length === 0 ? (
        <p className="panel__lead">Every company rule passed for this quotation.</p>
      ) : (
        <ul className="checks">
          {flagged.map((check) => (
            <CheckRow key={check.code} check={check} />
          ))}
        </ul>
      )}

      {passed.length > 0 ? (
        <details className="passes">
          <summary className="passes__summary">
            {passed.length} {passed.length === 1 ? 'check' : 'checks'} passed
          </summary>
          <ul className="passes__list">
            {passed.map((check) => (
              <li key={check.code} className="passes__row">
                <span className="check__rule">{check.rule_id ?? check.code}</span>
                <span>{check.title}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </Panel>
  )
}

function CheckRow({ check }: { check: CheckResult }) {
  return (
    <li className="check" data-status={check.status}>
      <span className="check__head">
        <CheckStatusLabel status={check.status} />
        <span className="check__rule">{check.rule_id ?? check.code}</span>
        <span className="check__title">{check.title}</span>
      </span>
      <p className="check__detail">{check.detail}</p>
      {(check.evidence ?? []).map((evidence, index) => (
        <blockquote key={`${evidence.source}-${index}`} className="evidence">
          <span className="evidence__source">
            {SOURCE_LABELS[evidence.source]}
            {evidence.field ? ` · ${evidence.field}` : ''}
          </span>
          <p className="evidence__text">&ldquo;{evidence.snippet}&rdquo;</p>
        </blockquote>
      ))}
    </li>
  )
}
