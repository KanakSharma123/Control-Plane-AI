"""Pipeline orchestration - the tiered check strategy.

The latency answer lives here. Every check has a known cost, speed and
detection power, so we run the cheapest sufficient one:

  TIER 0   deterministic, runs on every action, sub-millisecond
  TIER 1   secondary-model judge, runs only when Tier 0 flags something
           or the action is critical enough to be worth a second opinion

Whether Tier 1 runs *inline* or *asynchronously* is a policy decision,
not an engineering one. A customer chatbot with a 400 ms budget cannot
wait for it, so Tier 1 runs behind the response while the irreversible
consequence is held. A batch decision-support tool has room to wait.
Same engine, different policy - which is the point.
"""
import time
from typing import Dict, List, Optional

from src.control_engine import choose_control, get_policy
from src.criticality_engine import get_criticality
from src.detectors.consistency import check_consistency
from src.detectors.cost import check_cost
from src.detectors.grounding import check_grounding
from src.detectors.judge import run_tier1_judge
from src.detectors.responsibility import check_responsibility, redact
from src.health_engine import build_health
from src.models import Assessment, CheckResult

TIER1_RISK_TRIGGER = 3
TIER1_CRITICALITY_TRIGGER = 4
TIER1_CRITICAL_RISK_FLOOR = 2


def _aggregate_confidence(checks: List[CheckResult]) -> float:
    """Confidence in our own assessment, driven by the checks that fired.

    Weighted toward whichever check produced the worst score, because
    that is the one the decision rests on.
    """
    if not checks:
        return 0.5
    worst = max(c.score for c in checks)
    drivers = [c for c in checks if c.score == worst]
    return round(sum(c.confidence for c in drivers) / len(drivers), 2)


def should_run_tier1(risk: int, criticality_level: int) -> bool:
    """Escalate only when a second opinion is worth its latency.

    Tier 0 flagging something is the main trigger. High criticality alone
    is not: a clean, fully grounded payment release does not need a
    secondary model to confirm it is clean. Requiring at least a hint of
    risk before escalating on criticality is what keeps Tier 1 on a small
    share of traffic rather than all of it.
    """
    if risk >= TIER1_RISK_TRIGGER:
        return True
    return (
        criticality_level >= TIER1_CRITICALITY_TRIGGER
        and risk >= TIER1_CRITICAL_RISK_FLOOR
    )


def assess(
    case_id: str,
    use_case: str,
    action_type: str,
    source_context: str,
    generated_action: str,
    samples: Optional[List[str]] = None,
    actual_cost: float = 0.30,
    retries: int = 0,
    tool_calls: int = 1,
    learned_rules: Optional[List[Dict]] = None,
    force_tier1: Optional[bool] = None,
) -> Assessment:
    policy = get_policy(use_case)

    # ---- Tier 0 -----------------------------------------------------
    tier0_start = time.perf_counter()

    grounding = check_grounding(source_context, generated_action)
    consistency = check_consistency(samples or [])
    responsibility, responsibility_detail = check_responsibility(
        generated_action, source_context
    )
    cost = check_cost(action_type, actual_cost, retries, tool_calls)

    tier0_checks = [grounding, consistency, responsibility, cost]
    tier0_latency = (time.perf_counter() - tier0_start) * 1000

    criticality = get_criticality(action_type)
    interim = build_health(
        grounding, consistency, responsibility, responsibility_detail, cost
    )

    # ---- Tier 1, only when it is worth paying for --------------------
    tier1: Optional[CheckResult] = None
    tier1_latency = 0.0
    tier1_mode = "skipped"

    run_tier1 = (
        force_tier1
        if force_tier1 is not None
        else should_run_tier1(interim.blocking_risk, criticality.level)
    )

    if run_tier1:
        tier1 = run_tier1_judge(
            source_context,
            generated_action,
            [grounding.score, consistency.score],
        )
        if policy.get("tier1_inline", True):
            tier1_latency = tier1.latency_ms
            tier1_mode = "inline"
        else:
            # Runs behind the response. The user is not made to wait, but
            # the irreversible action stays held until it returns.
            tier1_latency = 0.0
            tier1_mode = "async (consequence held)"

    checks = tier0_checks + ([tier1] if tier1 else [])
    health = build_health(
        grounding,
        consistency,
        responsibility,
        responsibility_detail,
        cost,
        tier1=tier1,
    )

    confidence = _aggregate_confidence(
        [c for c in checks if c.detector != "cost"]
    )

    decision = choose_control(
        health=health,
        criticality=criticality,
        confidence=confidence,
        use_case=use_case,
        redactable=bool(responsibility.redactions),
        learned_rules=learned_rules,
        action_type=action_type,
        unverifiable=grounding.unverifiable,
    )

    redacted = None
    if decision.control == "EDIT" and responsibility.redactions:
        redacted = redact(generated_action, responsibility.redactions)

    return Assessment(
        case_id=case_id,
        use_case=use_case,
        action_type=action_type,
        source_context=source_context,
        generated_action=generated_action,
        health=health,
        criticality=criticality,
        decision=decision,
        checks=checks,
        tier0_latency_ms=round(tier0_latency, 3),
        tier1_latency_ms=round(tier1_latency, 1),
        tier1_ran=tier1 is not None,
        tier1_mode=tier1_mode,
        redacted_action=redacted,
    )
