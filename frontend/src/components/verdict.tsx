import { CHECK_STATUS_LABELS, DECISION_LABELS } from '@/ui/labels'
import type { CheckStatus, Decision } from '@/ui/labels'

/** The verdict is a stamp, not a pill: colour and weight carry it. */
export function Verdict({ decision }: { decision: Decision }) {
  return (
    <span className="verdict" data-decision={decision}>
      {DECISION_LABELS[decision]}
    </span>
  )
}

export function CheckStatusLabel({ status }: { status: CheckStatus }) {
  return <span className="check__status">{CHECK_STATUS_LABELS[status]}</span>
}
