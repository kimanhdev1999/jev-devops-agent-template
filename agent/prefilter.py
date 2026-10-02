"""Deterministic rules that resolve obvious cases before calling Jev at all.

This is where most of the cost/latency savings come from: a well-tuned prefilter
keeps the majority of traffic from ever reaching a model.
"""

from __future__ import annotations


def prefilter_ci_failure(log_tail: str) -> str | None:
    """Return a decision immediately if the log is unambiguous, else None."""
    lowered = log_tail.lower()
    if "connection refused" in lowered and "docker" in lowered:
        return "infra"
    if "out of memory" in lowered or "oomkilled" in lowered:
        return "infra"
    return None
