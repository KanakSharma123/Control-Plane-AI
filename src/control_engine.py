"""The decision engine: risk x criticality -> minimum necessary intervention.

Two ideas do the work here.

MINIMUM NECESSARY INTERVENTION
    The question is never "can I block this?" but "what is the least
    thing that makes this safe?". A leaked account number needs the
    number removed, not the paragraph destroyed. Blocking everything
    that looks risky is how a control layer earns itself a bypass.

UNCERTAINTY IS NOT GUILT
    Low confidence never escalates to BLOCK. If we are unsure, the right
    move is to look harder (VERIFY) or ask a person (HOLD) - not to
    punish the user for our own doubt. High risk with low confidence is a
    different situation from high risk with high confidence, and the
    ladder treats them differently.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from src.models import AIHealth, ControlDecision, DecisionCriticality

_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "policies.json"

LADDER = ["ALLOW", "MONITOR", "EDIT", "VERIFY", "HOLD", "BLOCK"]

# rows = blocking risk 1..5, cols = criticality 1..5
CONTROL_MATRIX: List[List[str]] = [
    ["ALLOW",   "ALLOW",   "ALLOW",   "MONITOR", "MONITOR"],
    ["ALLOW",   "ALLOW",   "MONITOR", "MONITOR", "VERIFY"],
    ["ALLOW",   "MONITOR", "VERIFY",  "VERIFY",  "HOLD"],
    ["MONITOR", "VERIFY",  "VERIFY",  "HOLD",    "HOLD"],
    ["VERIFY",  "VERIFY",  "HOLD",    "HOLD",    "BLOCK"],
]

CONFIDENCE_FLOOR = 0.70


@lru_cache(maxsize=1)
def _policies() -> Dict:
    with open(_POLICY_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def get_policy(use_case: str) -> Dict:
    data = _policies()
    return data["use_cases"].get(
        use_case, data["use_cases"][data["default_use_case"]]
    )


def known_use_cases() -> List[str]:
    return list(_policies()["use_cases"].keys())


def _shift(control: str, steps: int) -> str:
    idx = min(max(LADDER.index(control) + steps, 0), len(LADDER) - 1)
    return LADDER[idx]


def choose_control(
    health: AIHealth,
    criticality: DecisionCriticality,
    confidence: float,
    use_case: str = "internal_copilot",
    redactable: bool = False,
    learned_rules: Optional[List[Dict]] = None,
    action_type: str = "",
    unverifiable: bool = False,
) -> ControlDecision:
    policy = get_policy(use_case)
    rationale: List[str] = []

    risk = health.blocking_risk
    level = criticality.level

    # An unverifiable claim is harmless in a draft and serious in an
    # irreversible action. Rather than scoring "unknown" as risk
    # everywhere - which would flag most benign traffic - we let it raise
    # risk only where the consequence justifies the caution.
    if unverifiable and level >= 4:
        risk = min(risk + 1, 5)
        rationale.append(
            "The claim could not be verified against any source, and the "
            "action is high-criticality, so risk is raised one step."
        )

    control = CONTROL_MATRIX[risk - 1][level - 1]
    rationale.append(
        f"Blocking risk {risk}/5 against criticality {level}/5 "
        f"selects {control} from the policy matrix."
    )

    # A strict risk appetite means "escalate when something is flagged",
    # not "escalate everything". Applying the shift to clean traffic is
    # the fastest way to build an alert-fatigue problem.
    shift = policy.get("risk_shift", 0) if risk >= 3 else 0
    if shift:
        control = _shift(control, shift)
        rationale.append(
            f"'{policy['name']}' has a {policy['risk_appetite']} risk "
            f"appetite, shifting the response up {shift} rung to {control}."
        )

    # Redaction beats suppression whenever the finding is localised.
    if redactable and control in ("VERIFY", "HOLD", "BLOCK"):
        privacy = next(
            (s for s in health.responsibility_detail if s.name == "privacy"),
            None,
        )
        if privacy and privacy.score >= 4 and health.performance <= 3:
            control = "EDIT"
            rationale.append(
                "The finding is a localised identifier, so redacting it is "
                "sufficient; suppressing the whole action is not necessary."
            )

    escalated = False
    # Low confidence on a trivial, reversible action is not worth anyone's
    # attention. We only act on our own uncertainty where the consequence
    # makes it matter.
    if confidence < CONFIDENCE_FLOOR and level >= 3:
        if control == "BLOCK":
            control = "HOLD"
            escalated = True
            rationale.append(
                f"Assessment confidence {confidence:.0%} is below the "
                f"{CONFIDENCE_FLOOR:.0%} floor, so this goes to a human "
                f"rather than being blocked outright."
            )
        elif control in ("ALLOW", "MONITOR"):
            control = "VERIFY"
            escalated = True
            rationale.append(
                f"Assessment confidence {confidence:.0%} is below the floor, "
                f"so we verify before proceeding rather than trusting a "
                f"low-confidence pass."
            )

    # Cost never gates, but it must not vanish either.
    if health.cost >= 4 and control in ("ALLOW",):
        control = "MONITOR"
        rationale.append(
            f"Cost scored {health.cost}/5. That does not justify stopping "
            f"the action, but it is logged for budget review."
        )

    learned_note = None
    for rule in learned_rules or []:
        if rule.get("action_type") == action_type and rule.get("min_risk", 5) <= risk:
            if LADDER.index(rule["control"]) > LADDER.index(control):
                control = rule["control"]
                learned_note = rule["rule_id"]
                rationale.append(
                    f"Learned rule {rule['rule_id']} applies: a reviewer "
                    f"previously rejected this pattern, so it now escalates "
                    f"to {control} automatically."
                )

    return ControlDecision(
        control=control,
        confidence=confidence,
        reason=rationale[-1],
        rationale=rationale,
        escalated_for_uncertainty=escalated,
        learned_rule_applied=learned_note,
    )
