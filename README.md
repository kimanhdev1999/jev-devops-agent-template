# Jev DevOps Agent Template

A template for building DevOps automation agents on **Jev** (TypeSafe AI) instead of a
conventional LLM.

## Why Jev instead of an LLM here

Jev is not a text generator — it's a "smart `if` statement." You hand it unstructured
state (an alert, a log, a shell command) and it returns one of three typed, probabilistic
answers:

| Question type | Returns | Example use |
|---|---|---|
| **choice** | one of ≤255 predefined labels | route an alert to `page` / `ticket` / `ignore` |
| **score** | a 2–10 level scale you define | severity, confidence, risk level |
| **noul** | calibrated probability a statement is true | "is this CI failure a flake?" |

Compared to a conventional LLM pipeline:

- **Speed**: ~70–500ms vs. multi-second LLM round trips.
- **Cost**: fraction of a cent per decision; no output-token billing.
- **Reliability**: output is always a valid value from your schema — no JSON-parsing
  failures, no prompt-injection-shaped free text to sanitize.
- **Scope**: Jev is for narrow judgment calls ("which bucket?"), not prose generation,
  multi-step reasoning, or anything requiring exact counting/date arithmetic. Those stay
  in code or get escalated to a real LLM.

## Architecture

```
Signals -> Deterministic Prefilter -> Jev (judgment) -> Routing Code -> Action
                                                              |
                                                     (only if truly needed)
                                                              v
                                                         LLM for prose
```

- **Prefilter** (`agent/prefilter.py`) — cheap deterministic rules that resolve the
  obvious cases (regex, thresholds, allow/deny lists) before anything touches Jev. Most
  cost/latency savings come from never calling any model at all.
- **Jev client** (`agent/jev_client.py`) — thin wrapper around the three question types.
- **Router** (`agent/router.py`) — turns a Jev decision into an action. This is where
  your business logic and safety rules live — Jev never executes anything directly.
- **Shadow mode** (`agent/shadow.py`) — logs what Jev *would* decide without acting on
  it, so you can compare against ground truth before trusting it.
- **LLM escalation** (`agent/llm_escalation.py`) — optional fallback for the minority of
  cases that need generated prose (e.g., an incident summary) or reasoning Jev can't do.

## Included example use case

`examples/ci_failure_triage.py` — classifies a failing CI run as `flaky`, `regression`,
or `infra` and only triggers an automatic rerun for `flaky`.

Swap this out for your own: alert triage, command guardrails (read-only / reversible /
irreversible), log-bucket routing, etc.

## Quickstart

```bash
cp .env.example .env     # set JEV_API_KEY, JEV_BASE_URL
pip install -r requirements.txt
python -m examples.ci_failure_triage --shadow   # dry-run, logs only
python -m examples.ci_failure_triage            # live routing
pytest
```

## Rollout strategy (do this, don't skip it)

1. **Shadow mode** for 1–2 weeks: log Jev's decision next to what a human/existing
   system actually did. Don't act on it yet.
2. Compare agreement rate per label. Only automate the labels where Jev is
   consistently right and the blast radius of a wrong call is low.
3. Expand automation gradually. Keep irreversible actions behind a human or a
   deterministic guardrail (see `agent/router.py::GUARDRAILS`) regardless of Jev's
   confidence.

## Known limits (bake these into your prefilter, not into Jev prompts)

- Don't ask Jev to count, do arithmetic, or compare dates as quantities — do that in
  code before calling Jev.
- Calibration holds in aggregate, not per-call — a single "92% confidence" answer can
  still be wrong. Don't gate irreversible actions on a single call's confidence alone.
- English input performs best; other languages are unverified — route those to the
  LLM-escalation path or a human.
