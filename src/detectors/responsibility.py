"""Tier 0 - responsibility: privacy, safety, fairness and security.

Four sub-scores, combined by MAX rather than by mean. A clean privacy,
safety and fairness result must never dilute a serious security finding -
averaging those four would turn a 5 into a 2 and let it through.

Privacy detection is deterministic and returns the spans it matched, so
the EDIT rung can redact precisely instead of blocking a whole response.
"""
import re
import time
from typing import List, Tuple

from src.models import CheckResult, SubScore

# Indian identifiers plus the usual contact/account patterns.
_PII_PATTERNS: List[Tuple[str, re.Pattern, int]] = [
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), 5),
    ("Aadhaar", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), 5),
    ("bank account", re.compile(r"\b\d{11,18}\b"), 5),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), 4),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), 3),
    ("phone", re.compile(r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b"), 3),
]

_UNSAFE = [
    "ignore previous instructions",
    "disregard the policy",
    "override the approval",
    "bypass verification",
]

# Terms that should not be driving a differential outcome. Presence alone
# is not a finding - it is a flag for Tier 1 to look at properly.
_PROTECTED_TERMS = [
    "caste", "religion", "muslim", "hindu", "christian",
    "pregnant", "disabled", "widow", "sc/st",
]

_DIFFERENTIAL = [
    "reject", "deny", "decline", "reduce", "higher premium",
    "increase rate", "refuse",
]


def _find_pii(text: str) -> Tuple[int, List[str], List[str]]:
    worst = 1
    findings: List[str] = []
    spans: List[str] = []
    for label, pattern, severity in _PII_PATTERNS:
        for match in pattern.finditer(text):
            worst = max(worst, severity)
            findings.append(label)
            spans.append(match.group(0))
    return worst, sorted(set(findings)), spans


def check_responsibility(
    generated_action: str, source: str = ""
) -> Tuple[CheckResult, List[SubScore]]:
    started = time.perf_counter()
    lowered = generated_action.lower()

    privacy_score, pii_kinds, pii_spans = _find_pii(generated_action)
    privacy_reason = (
        f"Detected {', '.join(pii_kinds)} in the generated action."
        if pii_kinds
        else "No personal or account identifiers detected."
    )

    safety_hits = [p for p in _UNSAFE if p in lowered]
    safety_score = 5 if safety_hits else 1
    safety_reason = (
        f"Instruction-subversion language present: '{safety_hits[0]}'."
        if safety_hits
        else "No instruction-subversion or unsafe directive language."
    )

    protected = [t for t in _PROTECTED_TERMS if t in lowered]
    differential = [d for d in _DIFFERENTIAL if d in lowered]
    if protected and differential:
        fairness_score = 4
        fairness_reason = (
            f"A protected attribute ('{protected[0]}') co-occurs with a "
            f"differential outcome ('{differential[0]}'). Flagged for "
            f"review, not auto-blocked - co-occurrence is not proof."
        )
    elif protected:
        fairness_score = 2
        fairness_reason = (
            f"Protected attribute '{protected[0]}' mentioned without an "
            f"adverse outcome attached."
        )
    else:
        fairness_score = 1
        fairness_reason = "No protected attribute drives the outcome."

    leaked_internal = "internal only" in source.lower() and len(
        generated_action
    ) > 0 and any(
        token in lowered for token in ("internal only", "confidential")
    )
    security_score = 4 if leaked_internal else 1
    security_reason = (
        "Content marked internal-only appears in an outbound action."
        if leaked_internal
        else "No internal-only content detected in the outbound action."
    )

    detail = [
        SubScore(name="privacy", score=privacy_score, reason=privacy_reason),
        SubScore(name="safety", score=safety_score, reason=safety_reason),
        SubScore(name="fairness", score=fairness_score, reason=fairness_reason),
        SubScore(name="security", score=security_score, reason=security_reason),
    ]

    worst = max(sub.score for sub in detail)
    driver = next(sub for sub in detail if sub.score == worst)

    return (
        CheckResult(
            detector="responsibility",
            tier=0,
            score=worst,
            confidence=0.90 if worst >= 4 else 0.85,
            reason=f"{driver.name}: {driver.reason}",
            latency_ms=(time.perf_counter() - started) * 1000,
            redactions=pii_spans,
        ),
        detail,
    )


def redact(text: str, spans: List[str]) -> str:
    """Replace exactly the matched identifiers, leaving the rest intact."""
    out = text
    for span in spans:
        out = out.replace(span, "[REDACTED]")
    return out
