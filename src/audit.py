"""Audit trail and the feedback loop.

Every assessment is appended to a JSONL trail. Every human override is
recorded against the assessment it overturned, and an override that
escalates becomes a learned rule: the next action of the same type at the
same or higher risk is caught automatically.

That is the compounding claim made in the pitch, made concrete - one
human decision becomes a future control.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from src.control_engine import LADDER
from src.models import Assessment

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AUDIT_LOG = DATA_DIR / "audit_log.jsonl"
RULES_FILE = DATA_DIR / "learned_rules.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_assessment(assessment: Assessment) -> Dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": _now(),
        "event": "assessment",
        "case_id": assessment.case_id,
        "use_case": assessment.use_case,
        "action_type": assessment.action_type,
        "scorecard": assessment.scorecard(),
        "control": assessment.decision.control,
        "confidence": assessment.decision.confidence,
        "rationale": assessment.decision.rationale,
        "tier1_ran": assessment.tier1_ran,
        "tier1_mode": assessment.tier1_mode,
        "tier0_latency_ms": assessment.tier0_latency_ms,
        "tier1_latency_ms": assessment.tier1_latency_ms,
        "checks": [
            {
                "detector": c.detector,
                "tier": c.tier,
                "score": c.score,
                "confidence": c.confidence,
                "reason": c.reason,
            }
            for c in assessment.checks
        ],
    }
    with open(AUDIT_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load_rules() -> List[Dict]:
    if not RULES_FILE.exists():
        return []
    with open(RULES_FILE, encoding="utf-8") as handle:
        return json.load(handle)


def save_rules(rules: List[Dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RULES_FILE, "w", encoding="utf-8") as handle:
        json.dump(rules, handle, indent=2)


def record_override(
    assessment: Assessment,
    reviewer_verdict: str,
    reviewer_note: str = "",
    reviewer: str = "reviewer@enterprise",
) -> Optional[Dict]:
    """Log a human decision and, where it escalates, learn from it.

    An override that *relaxes* the control is logged but never learned
    from automatically - loosening a control is exactly the direction in
    which a single reviewer's judgement should not silently propagate.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": _now(),
        "event": "override",
        "case_id": assessment.case_id,
        "system_control": assessment.decision.control,
        "reviewer_verdict": reviewer_verdict,
        "reviewer": reviewer,
        "note": reviewer_note,
    }
    with open(AUDIT_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    escalation = (
        reviewer_verdict in LADDER
        and LADDER.index(reviewer_verdict) > LADDER.index(assessment.decision.control)
    ) or reviewer_verdict == "REJECT"

    if not escalation:
        return None

    rules = load_rules()
    rule_id = f"LR-{len(rules) + 1:03d}"
    rule = {
        "rule_id": rule_id,
        "learned_from": assessment.case_id,
        "action_type": assessment.action_type,
        "min_risk": assessment.health.blocking_risk,
        "control": "HOLD" if reviewer_verdict == "REJECT" else reviewer_verdict,
        "note": reviewer_note or "Learned from a reviewer escalation.",
        "created": _now(),
    }
    rules.append(rule)
    save_rules(rules)
    return rule


def read_audit(limit: int = 50) -> List[Dict]:
    if not AUDIT_LOG.exists():
        return []
    with open(AUDIT_LOG, encoding="utf-8") as handle:
        lines = handle.readlines()
    return [json.loads(line) for line in lines[-limit:]]


def reset() -> None:
    for path in (AUDIT_LOG, RULES_FILE):
        if path.exists():
            path.unlink()
