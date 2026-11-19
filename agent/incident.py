"""Incident decision with Claude Haiku 5.5 on the Claude API.

Jev is on hold for now, so Haiku makes the decision Jev was going to make. It
is kept Jev-shaped on purpose: one call, one narrow question, and a typed answer
validated against a schema (structured outputs). Haiku never sees or produces a
command; routing and every safety rule stay in `agent.router`.

Differences from Jev to keep in mind:
- `confidence` is the model's own estimate, not a calibrated probability. The
  router never gates on it alone (it also needs a deterministic signal).
- The same call writes the human-readable summary for Slack/Jira, so there is
  no separate "LLM escalation" step.

Swapping Jev back in later means replacing `decide()` with Jev choice/score/noul
calls that fill the same `IncidentDecision` fields.
"""

from __future__ import annotations

import os
from typing import Literal

import anthropic
from pydantic import BaseModel

ROOT_CAUSES = ("bad_deploy", "db_outage", "oom", "image_pull", "traffic_spike", "unknown")
RootCause = Literal["bad_deploy", "db_outage", "oom", "image_pull", "traffic_spike", "unknown"]

DEFAULT_MODEL = "claude-haiku-5-5"


class IncidentDecision(BaseModel):
    root_cause: RootCause
    severity: int  # 2 (cosmetic) .. 10 (full outage); clamped after parsing
    rollback_likely_fixes: bool
    confidence: float  # 0.0-1.0, self-reported by the model, NOT calibrated
    evidence: list[str]  # short facts/quotes from the input that support the call
    summary: str  # 2-4 plain sentences for the Slack message / Jira ticket


SYSTEM_PROMPT = """You are the triage step of an on-call agent for a Kubernetes service.
You receive evidence that code has already collected about one CloudWatch alarm:
a sample of recent error log lines (PII already masked), metric counts, and the
Deployment's rollout history. Decide what most likely went wrong.

root_cause, pick exactly one:
- bad_deploy: errors started right after a new revision rolled out, and the old
  revision did not have them (a config or code change in the new version).
- db_outage: the database itself is down or unreachable for every version,
  including revisions that were healthy before.
- oom: containers are being OOMKilled or are running out of memory.
- image_pull: pods cannot pull or start their image.
- traffic_spike: errors scale with a sudden rise in request volume.
- unknown: the evidence does not support any of the above.

severity: 2 = cosmetic, 5 = degraded for some users, 8 = most requests failing,
10 = full outage.
rollback_likely_fixes: true only if returning to the previous revision would
plausibly stop the errors.
confidence: your own estimate from 0.0 to 1.0. Use a low value when the evidence
is thin or conflicting.
evidence: 2-5 short facts copied or paraphrased from the input. Do not invent any.
summary: 2-4 plain sentences for an on-call engineer: what is failing, since
when, the likely cause, and what you suggest. Never include commands."""


def _client() -> anthropic.Anthropic:
    # Reads ANTHROPIC_API_KEY. The analyzer Lambda passes its own client built
    # from the config secret instead.
    return anthropic.Anthropic()


def decide(
    evidence_text: str,
    *,
    model: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> IncidentDecision | None:
    """Ask Haiku for a typed incident decision.

    Returns None when the model declines (refusal) or the answer can't be used;
    the caller must then hold for a human instead of guessing.
    """
    client = client or _client()
    try:
        response = client.messages.parse(
            model=model or os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
            # Classification: effort low keeps thinking short; the cap leaves room
            # for thinking plus the JSON answer.
            max_tokens=4096,
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": evidence_text}],
            output_format=IncidentDecision,
        )
    except anthropic.RateLimitError:
        raise  # let Lambda/EventBridge retry
    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500:
            raise  # transient, retry
        return None  # 4xx: bad request / no access -> human

    if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
        return None

    decision = response.parsed_output
    decision.severity = min(10, max(2, decision.severity))
    decision.confidence = min(1.0, max(0.0, decision.confidence))
    return decision
