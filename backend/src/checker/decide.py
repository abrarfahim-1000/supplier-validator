"""Apply decision precedence and build the reason list.

Any reject hit wins over any needs-person hit; no hits means approve. Every check already
ran, so this module never short-circuits and never re-evaluates a rule.
"""

from __future__ import annotations

from collections.abc import Sequence

from checker.schemas import (
    CheckResult,
    CheckStatus,
    Decision,
    DecisionVerdict,
    Reason,
)

_STATUS_RANK = {
    CheckStatus.REJECT: 0,
    CheckStatus.NEEDS_PERSON: 1,
    CheckStatus.PASS: 2,
}


def decide(checks: Sequence[CheckResult]) -> DecisionVerdict:
    if any(check.status is CheckStatus.REJECT for check in checks):
        decision = Decision.REJECT
    elif any(check.status is CheckStatus.NEEDS_PERSON for check in checks):
        decision = Decision.NEEDS_PERSON
    else:
        decision = Decision.APPROVE

    triggered = [check for check in checks if check.status is not CheckStatus.PASS]
    ordered = sorted(triggered, key=lambda check: _STATUS_RANK[check.status])
    reasons = [
        Reason(
            code=check.code,
            rule_id=check.rule_id,
            title=check.title,
            detail=check.detail,
            evidence=check.evidence,
        )
        for check in ordered
    ]
    return DecisionVerdict(decision=decision, reasons=reasons)
