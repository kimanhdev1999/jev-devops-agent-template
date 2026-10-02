"""Example: classify a failing CI run and decide whether to auto-rerun it.

    python -m examples.ci_failure_triage --shadow   # log only, no action
    python -m examples.ci_failure_triage            # live routing
"""

from __future__ import annotations

import argparse

from rich.console import Console

from agent.jev_client import JevClient
from agent.prefilter import prefilter_ci_failure
from agent.router import route_ci_failure
from agent.shadow import log_decision

console = Console()

LABELS = ["flaky", "regression", "infra"]

QUESTION = (
    "This is the tail of a failing CI job's log output. Classify the failure as "
    "'flaky' (intermittent, passes on rerun, e.g. timing/network blips), "
    "'regression' (a real code change broke behavior), or "
    "'infra' (the CI environment itself is broken, e.g. runner/network/disk issues)."
)

SAMPLE_LOG = """
FAIL tests/test_checkout.py::test_submit_order
AssertionError: expected status 200, got 504
flaky: connection to payment-mock timed out after 2000ms
"""


def classify(log_tail: str) -> tuple[str, float]:
    prefiltered = prefilter_ci_failure(log_tail)
    if prefiltered is not None:
        return prefiltered, 1.0  # deterministic match, full confidence

    with JevClient() as jev:
        result = jev.choice(state=log_tail, question=QUESTION, options=LABELS)
        return result.label, result.confidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow", action="store_true", help="log only, don't act")
    args = parser.parse_args()

    label, confidence = classify(SAMPLE_LOG)
    decision = route_ci_failure(label, confidence)

    if args.shadow:
        log_decision(input_summary=SAMPLE_LOG.strip()[:200], label=label, confidence=confidence, would_do=decision.action)
        console.print(f"[yellow]SHADOW[/yellow] label={label} confidence={confidence:.2f} would_do={decision.action}")
        return

    console.print(f"label={label} confidence={confidence:.2f} action={decision.action}")
    if decision.action == "rerun":
        console.print("[green]-> triggering automatic rerun[/green]")
    elif decision.action == "escalate":
        console.print("[yellow]-> paging infra on-call[/yellow]")
    else:
        console.print("[red]-> holding for human review[/red]")


if __name__ == "__main__":
    main()
