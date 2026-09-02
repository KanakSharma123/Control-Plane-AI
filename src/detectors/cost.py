"""Tier 0 - cost, scored against the expected envelope for the task.

We deliberately do not score raw spend. A genuinely hard query should
cost more; flagging it would punish the system's best work. What we score
is spend relative to what this task type is expected to consume, which
makes retries, agent loops and needless model escalation visible while
leaving legitimately expensive work alone.
"""
import time
from typing import Dict

from src.models import CheckResult

# Expected cost envelope per action type, in rupees per interaction.
EXPECTED_COST: Dict[str, float] = {
    "claim_approval": 0.90,
    "payment_release": 0.90,
    "policy_answer": 0.35,
    "customer_email": 0.25,
    "document_summary": 0.40,
    "internal_lookup": 0.20,
}

DEFAULT_EXPECTED = 0.40


def check_cost(
    action_type: str,
    actual_cost: float,
    retries: int = 0,
    tool_calls: int = 0,
) -> CheckResult:
    started = time.perf_counter()

    expected = EXPECTED_COST.get(action_type, DEFAULT_EXPECTED)
    ratio = actual_cost / expected if expected else 1.0

    if ratio <= 1.2:
        score, reason = 1, f"Within the expected envelope ({ratio:.1f}x)."
    elif ratio <= 2.0:
        score, reason = 2, f"Mildly above expected ({ratio:.1f}x)."
    elif ratio <= 3.5:
        score, reason = 3, f"Materially above expected ({ratio:.1f}x)."
    elif ratio <= 6.0:
        score, reason = 4, f"Heavily above expected ({ratio:.1f}x)."
    else:
        score, reason = 5, f"Runaway spend ({ratio:.1f}x expected)."

    drivers = []
    if retries:
        drivers.append(f"{retries} retry/retries")
    if tool_calls > 3:
        drivers.append(f"{tool_calls} tool calls")
    if drivers:
        reason += " Driven by " + " and ".join(drivers) + "."

    return CheckResult(
        detector="cost",
        tier=0,
        score=score,
        confidence=0.95,
        reason=(
            f"\u20b9{actual_cost:.2f} against \u20b9{expected:.2f} expected. "
            + reason
        ),
        latency_ms=(time.perf_counter() - started) * 1000,
    )
