"""Core data model for ControlPlane.

SCORING CONVENTION (applies to every score in this system):

    1 = low concern   ...   5 = high concern

This is deliberately uniform. A high number always means "worry more",
whether it is a health score or a criticality score. Nothing in this
codebase inverts it.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class SubScore(BaseModel):
    """One named contributor to a score, with the evidence behind it."""

    name: str
    score: int = Field(ge=1, le=5)
    reason: str


class AIHealth(BaseModel):
    """How likely is the model to be wrong, wasteful or unsafe?"""

    performance: int = Field(ge=1, le=5)
    cost: int = Field(ge=1, le=5)
    responsibility: int = Field(ge=1, le=5)

    performance_detail: List[SubScore] = []
    responsibility_detail: List[SubScore] = []
    cost_detail: List[SubScore] = []

    @property
    def blocking_risk(self) -> int:
        """Risk that is allowed to gate an action.

        Cost is deliberately excluded. An expensive answer is a budget
        problem, not a safety problem: it belongs in monitoring, not in
        the decision to stop something happening.
        """
        return max(self.performance, self.responsibility)


class DecisionCriticality(BaseModel):
    """How much does it matter if the model is wrong?"""

    impact: int = Field(ge=1, le=5)
    reversibility: int = Field(ge=1, le=5)
    label: str = ""

    @property
    def level(self) -> int:
        # Conservative by design: a modest-impact but irreversible action
        # is still treated as critical.
        return max(self.impact, self.reversibility)


class CheckResult(BaseModel):
    """Output of a single detector."""

    detector: str
    tier: int
    score: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    latency_ms: float = 0.0
    redactions: List[str] = []

    # A detector that had nothing to work on is not evidence of safety.
    # It is excluded from scoring and reported as inapplicable, rather
    # than contributing a middling score that quietly inflates risk.
    applicable: bool = True

    # True when a claim exists but could not be checked against anything.
    # Harmless on a draft, serious on an irreversible action - so it is
    # carried through to the decision rather than resolved here.
    unverifiable: bool = False


class ControlDecision(BaseModel):
    control: str
    confidence: float
    reason: str
    rationale: List[str] = []
    escalated_for_uncertainty: bool = False
    learned_rule_applied: Optional[str] = None


class Assessment(BaseModel):
    """Everything ControlPlane concluded about one AI action."""

    case_id: str
    use_case: str
    action_type: str
    source_context: str
    generated_action: str

    health: AIHealth
    criticality: DecisionCriticality
    decision: ControlDecision
    checks: List[CheckResult] = []

    tier0_latency_ms: float = 0.0
    tier1_latency_ms: float = 0.0
    tier1_ran: bool = False
    tier1_mode: str = "skipped"
    redacted_action: Optional[str] = None

    def total_latency_ms(self) -> float:
        return self.tier0_latency_ms + self.tier1_latency_ms

    def scorecard(self) -> Dict[str, int]:
        return {
            "performance": self.health.performance,
            "cost": self.health.cost,
            "responsibility": self.health.responsibility,
            "impact": self.criticality.impact,
            "reversibility": self.criticality.reversibility,
        }
