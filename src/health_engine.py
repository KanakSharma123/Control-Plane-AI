"""AI Health - how likely is the model to be wrong, wasteful or unsafe?

Three scores, each built from named sub-scores so every number on the
scorecard can be traced to the evidence that produced it.

Aggregation rules, and why:

  performance    = max(grounding, consistency)
                   A claim can be internally consistent and still
                   ungrounded, or grounded once and unstable across
                   samples. Either is a reason to worry, so we take the
                   worse of the two rather than blending them.

  responsibility = max(privacy, safety, fairness, security)
                   Averaging would let three clean sub-scores bury one
                   serious finding. A critical violation is never
                   diluted by averaging.

  cost           = as scored, and never used to gate an action.
"""
from typing import List, Optional

from src.models import AIHealth, CheckResult, SubScore


def build_health(
    grounding: CheckResult,
    consistency: CheckResult,
    responsibility: CheckResult,
    responsibility_detail: List[SubScore],
    cost: CheckResult,
    tier1: Optional[CheckResult] = None,
) -> AIHealth:
    performance_detail = [
        SubScore(name="grounding", score=grounding.score, reason=grounding.reason),
        SubScore(
            name="consistency", score=consistency.score, reason=consistency.reason
        ),
    ]

    # A detector that could not run contributes nothing. Scoring it in the
    # middle would let missing evidence masquerade as mild risk, which is
    # how a checker ends up flagging most of its own traffic.
    applicable = [c.score for c in (grounding, consistency) if c.applicable]
    performance = max(applicable) if applicable else 1

    if tier1 is not None:
        # Tier 1 is the more expensive, better-informed opinion. It is
        # allowed to move performance in either direction - including
        # down, which is what stops escalation from being a ratchet that
        # only ever raises alarm.
        performance_detail.append(
            SubScore(name="tier1_judge", score=tier1.score, reason=tier1.reason)
        )
        performance = tier1.score

    return AIHealth(
        performance=performance,
        cost=cost.score,
        responsibility=responsibility.score,
        performance_detail=performance_detail,
        responsibility_detail=responsibility_detail,
        cost_detail=[SubScore(name="cost", score=cost.score, reason=cost.reason)],
    )
