"""Turns a Jev decision into an action. Business logic and safety rules live here —
Jev only classifies, it never executes anything.
"""

from __future__ import annotations

from dataclasses import dataclass

# Actions that must never auto-execute regardless of Jev's confidence.
# Route these to a human or a deterministic approval step instead.
GUARDRAILS: set[str] = {"regression"}

MIN_CONFIDENCE_TO_AUTOMATE = 0.85


@dataclass
class RoutingDecision:
    label: str
    confidence: float
    action: str  # "rerun" | "escalate" | "hold_for_human"


def route_ci_failure(label: str, confidence: float) -> RoutingDecision:
    if label in GUARDRAILS:
        return RoutingDecision(label, confidence, action="hold_for_human")
    if label == "flaky" and confidence >= MIN_CONFIDENCE_TO_AUTOMATE:
        return RoutingDecision(label, confidence, action="rerun")
    if label == "infra":
        return RoutingDecision(label, confidence, action="escalate")
    # Low confidence on any label: don't trust a single call, send to a human.
    return RoutingDecision(label, confidence, action="hold_for_human")
