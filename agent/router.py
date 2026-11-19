"""Turns a model decision into an action. Business logic and safety rules live here —
the model only classifies, it never executes anything.
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


# ---------------------------------------------------------------------------
# Kubernetes incident routing (EKS demo)
# ---------------------------------------------------------------------------


@dataclass
class IncidentRoute:
    action: str  # "offer_rollback" | "ticket_only" | "hold_for_human"
    reason: str


def route_incident(
    root_cause: str | None,
    rollback_likely_fixes: bool,
    confidence: float,
    *,
    new_revision_in_window: bool,
    min_confidence: float = MIN_CONFIDENCE_TO_AUTOMATE,
) -> IncidentRoute:
    """Decide whether the Slack message gets an [Approve rollback] button.

    Even then nothing runs until a human clicks it. The button is offered only
    when the model's call AND a fact computed in code agree:
      - root_cause is bad_deploy and the model thinks a rollback fixes it,
      - its (uncalibrated) confidence clears the bar, and
      - code saw a new Deployment revision shortly before the alarm.
    """
    if root_cause is None:
        return IncidentRoute("hold_for_human", "model gave no usable decision")
    if root_cause != "bad_deploy":
        return IncidentRoute("ticket_only", f"root cause {root_cause}: a rollback wouldn't help")
    if not new_revision_in_window:
        return IncidentRoute("hold_for_human", "model says bad_deploy but no recent rollout was found")
    if not rollback_likely_fixes:
        return IncidentRoute("hold_for_human", "model doesn't expect a rollback to fix it")
    if confidence < min_confidence:
        return IncidentRoute("hold_for_human", f"confidence {confidence:.2f} below {min_confidence:.2f}")
    return IncidentRoute("offer_rollback", "bad deploy confirmed by recent rollout")
