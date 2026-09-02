"""Tier 0 - self-consistency across sampled generations.

In production this samples the model n times at non-zero temperature and
measures divergence on the load-bearing claim. The prototype accepts
pre-recorded samples on the case so the mechanism is demonstrable without
live model calls. Where a case carries no samples we return 3 (unknown)
rather than inventing agreement.
"""
import time
from typing import List

from src.detectors.grounding import extract_amounts, extract_numbers
from src.models import CheckResult


def check_consistency(samples: List[str]) -> CheckResult:
    started = time.perf_counter()

    if not samples or len(samples) < 2:
        return CheckResult(
            detector="consistency",
            tier=0,
            score=1,
            confidence=0.30,
            reason=(
                "Not enough sampled generations to measure divergence; "
                "this check did not apply and does not count toward risk."
            ),
            latency_ms=(time.perf_counter() - started) * 1000,
            applicable=False,
        )

    per_sample = [extract_amounts(s) for s in samples]
    headline = [vals[0] for vals in per_sample if vals]

    applicable = True
    if len(headline) < 2:
        # No monetary claim to compare, so fall back to the numeric tokens
        # the samples assert - clause numbers, day counts, percentages.
        # Divergence there is the same signal in a different costume.
        token_sets = [tuple(sorted(extract_numbers(s))) for s in samples]
        distinct = {t for t in token_sets if t}
        if len(distinct) > 1:
            score, confidence = 4, 0.84
            reason = (
                f"Sampled generations assert different figures across "
                f"{len(distinct)} variants; the model is not stable on "
                f"this claim."
            )
        else:
            score, confidence, applicable = 1, 0.35, False
            reason = "Samples share no comparable claim to disagree on."
    elif len(set(headline)) == 1:
        score, confidence = 1, 0.92
        reason = f"All {len(samples)} sampled generations agree."
    else:
        spread = (max(headline) - min(headline)) / max(headline)
        score = 5 if spread > 0.10 else 4
        confidence = 0.88
        reason = (
            f"Sampled generations disagree across {len(set(headline))} "
            f"distinct values (spread {spread:.0%}); the model is not "
            f"stable on this claim."
        )

    return CheckResult(
        detector="consistency",
        tier=0,
        score=score,
        confidence=confidence,
        reason=reason,
        latency_ms=(time.perf_counter() - started) * 1000,
        applicable=applicable,
    )
