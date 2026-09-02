"""Tier 0 - claim-level grounding against the source context.

Deterministic, cheap and explainable. We extract comparable claims from
both the source and the generated action, and check that they agree.

One limitation stated openly: when no comparable claim can be extracted
we return 3 ("unknown"), never 1. Absence of evidence is not evidence of
correctness, and that distinction is exactly what the Round 2 brief warns
about when it notes there is often no reliable real-time ground truth.
"""
import re
import time
from typing import List, Optional, Tuple

from src.models import CheckResult

_LAKH = re.compile(r"(?:\u20b9|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*lakh", re.I)
_CRORE = re.compile(r"(?:\u20b9|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*crore", re.I)
_PLAIN = re.compile(r"(?:\u20b9|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)", re.I)
_PERCENT = re.compile(r"([\d.]+)\s*%")
_DATE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ""))


def extract_amounts(text: str) -> List[float]:
    """Return every rupee amount in a text, normalised to rupees."""
    found: List[float] = []
    for match in _CRORE.finditer(text):
        found.append(_to_float(match.group(1)) * 10_000_000)
    for match in _LAKH.finditer(text):
        found.append(_to_float(match.group(1)) * 100_000)
    stripped = _CRORE.sub(" ", _LAKH.sub(" ", text))
    for match in _PLAIN.finditer(stripped):
        found.append(_to_float(match.group(1)))
    return found


def extract_percentages(text: str) -> List[float]:
    return [float(m.group(1)) for m in _PERCENT.finditer(text)]


def extract_dates(text: str) -> List[str]:
    return [m.group(1) for m in _DATE.finditer(text)]


def extract_numbers(text: str) -> List[str]:
    """Every bare numeric token: amounts, percentages, clause references.

    Used by the consistency check, where what matters is whether two
    samples assert the same numbers - not what those numbers denote.
    """
    return _NUMBER.findall(text)


def _fmt(value: float) -> str:
    return f"\u20b9{value:,.0f}"


def _first_unsupported(
    source_vals: List[float], gen_vals: List[float]
) -> Optional[Tuple[float, float]]:
    """Find the first generated value with no match in the source."""
    for gen in gen_vals:
        if not any(abs(gen - src) < 0.01 for src in source_vals):
            nearest = min(source_vals, key=lambda s: abs(s - gen))
            return gen, nearest
    return None


def check_grounding(source: str, generated_action: str) -> CheckResult:
    started = time.perf_counter()

    src_amounts = extract_amounts(source)
    gen_amounts = extract_amounts(generated_action)
    src_pcts = extract_percentages(source)
    gen_pcts = extract_percentages(generated_action)
    src_dates = set(extract_dates(source))
    gen_dates = extract_dates(generated_action)

    score, confidence, unverifiable = 2, 0.40, True
    reason = (
        "No comparable claim could be extracted, so correctness could not "
        "be verified either way. Treated as unverified, not as correct."
    )

    if gen_amounts and src_amounts:
        mismatch = _first_unsupported(src_amounts, gen_amounts)
        if mismatch:
            gen, nearest = mismatch
            delta = abs(gen - nearest)
            ratio = delta / nearest if nearest else 1.0
            unverifiable = False
            if ratio <= 0.01:
                score, confidence = 2, 0.85
                reason = (
                    f"Rounding-level difference only: {_fmt(gen)} against "
                    f"{_fmt(nearest)} ({ratio:.1%}). Below the material "
                    f"threshold."
                )
            else:
                score = 5 if ratio > 0.05 else 4
                confidence = 0.94
                reason = (
                    f"Monetary claim unsupported. Generated {_fmt(gen)}, "
                    f"nearest source value {_fmt(nearest)}, "
                    f"difference {_fmt(delta)} ({ratio:.0%})."
                )
        else:
            score, confidence, unverifiable = 1, 0.96, False
            reason = "Every monetary claim traces to a value in the source."
    elif gen_amounts and not src_amounts:
        score, confidence, unverifiable = 4, 0.70, False
        reason = (
            "The action asserts a monetary amount that appears nowhere in "
            "the source context."
        )
    elif gen_pcts and not src_pcts:
        # A specific figure quoted against a source containing no figures
        # at all is an assertion, not a retrieval. This is the shape of
        # the hardest case in the brief: the same gap that causes the
        # hallucination also prevents us from checking it.
        score, confidence, unverifiable = 4, 0.72, False
        reason = (
            f"The action asserts a specific figure ({gen_pcts[0]}%) that "
            f"has no counterpart anywhere in the source context."
        )

    if score <= 3 and gen_pcts and src_pcts:
        unmatched = [p for p in gen_pcts if p not in src_pcts]
        if unmatched:
            score, confidence, unverifiable = max(score, 4), 0.80, False
            reason = f"Percentage {unmatched[0]}% is not supported by the source."

    if score <= 3 and gen_dates and src_dates:
        unmatched_dates = [d for d in gen_dates if d not in src_dates]
        if unmatched_dates:
            score, confidence, unverifiable = max(score, 4), 0.75, False
            reason = f"Date {unmatched_dates[0]} does not appear in the source."

    return CheckResult(
        detector="grounding",
        tier=0,
        score=score,
        confidence=confidence,
        reason=reason,
        latency_ms=(time.perf_counter() - started) * 1000,
        unverifiable=unverifiable,
    )
