# Jev Kubernetes Agent Template

A template for building an operations agent for a **Kubernetes cluster** on **Jev**
(TypeSafe AI) instead of a conventional LLM. The agent watches cluster signals (pod
status, events, alerts, logs, proposed `kubectl` commands), asks Jev narrow typed
questions about them, and routes the answer to a safe, pre-approved action such as
restarting a pod, opening a ticket, paging on-call, or holding for a human.

## Why Jev instead of an LLM here

Jev is not a text generator. Think of it as a "smart `if` statement." You hand it
unstructured cluster state (a pod's events, a container log tail, an Alertmanager
alert, a `kubectl` command) and it returns one of three typed, probabilistic answers:

| Question type | Returns | Kubernetes example |
|---|---|---|
| **choice** | one of ≤255 predefined labels | classify a failing pod as `oom` / `bad_config` / `image_pull` / `crash_bug` / `node_issue` |
| **score** | a 2–10 level scale you define | blast-radius or severity of an alert for a given namespace |
| **noul** | calibrated probability a statement is true | "is this `kubectl` command read-only?" |

Compared to a conventional LLM pipeline:

- **Speed**: ~70–500ms vs. multi-second LLM round trips, fast enough to sit in an
  event/alert loop.
- **Cost**: fraction of a cent per decision; no output-token billing, so it's
  affordable to evaluate every pod event, not just sampled ones.
- **Reliability**: output is always a valid value from your schema. No JSON-parsing
  failures, and no free-text output that could be turned into a cluster command.
- **Scope**: Jev is for narrow judgment calls ("which bucket?"), not prose generation,
  multi-step reasoning, or anything requiring exact counting/date arithmetic (restart
  counts, replica math, age comparisons). Those stay in code or get escalated to a
  real LLM.

## Architecture

```
Cluster signals              Deterministic        Jev           Routing code       Action
(pod status, k8s events, ->  Prefilter      ->  (judgment) ->  + guardrails  ->  (restart pod,
 Alertmanager alerts,                                                |            ticket, page,
 container logs,                                                     |            hold for human)
 proposed kubectl cmds)                                   (only if truly needed)
                                                                     v
                                                                LLM for prose
                                                         (incident summary / handoff)
```

- **Prefilter** (`agent/prefilter.py`): cheap deterministic rules that resolve the
  obvious cases before anything touches Jev, e.g. a container `lastState.terminated.reason`
  of `OOMKilled`, a pod stuck in `ImagePullBackOff`, `NodeNotReady` events, or a
  namespace on an allow/deny list. Most cost/latency savings come from never calling
  any model at all.
- **Jev client** (`agent/jev_client.py`): thin wrapper around the three question types.
- **Router** (`agent/router.py`): turns a Jev decision into a cluster action. This is
  where your business logic and safety rules live. Jev never runs `kubectl` or calls
  the Kubernetes API itself.
- **Shadow mode** (`agent/shadow.py`): logs what Jev *would* decide without touching the
  cluster, so you can compare against what on-call actually did before trusting it.
- **LLM escalation** (`agent/llm_escalation.py`): optional fallback for the minority of
  cases that need generated prose (e.g., an incident summary for the on-call handoff) or
  reasoning Jev can't do.

## Kubernetes use cases this template is shaped for

- **Pod failure triage**: classify `CrashLoopBackOff` / `Error` pods from events and log
  tails, then auto-restart only the transient ones and escalate the rest.
- **Alert routing**: decide whether an Alertmanager alert should `page`, `ticket`, or be
  `ignore`d, scored by severity and namespace criticality.
- **Command guardrails**: classify a proposed `kubectl`/`helm` command as `read_only`,
  `reversible` (e.g. `rollout restart`, `scale`), or `irreversible` (e.g. `delete pvc`,
  `delete namespace`) before an operator or another agent runs it.
- **Event/log bucketing**: route noisy cluster events and container logs to the right
  team or channel.

## Included example

`examples/ci_failure_triage.py` classifies a failing CI run (for example, a pipeline
deploying to the cluster) as `flaky`, `regression`, or `infra`, and only triggers an
automatic rerun for `flaky`. It shows the full prefilter → Jev → router → shadow flow
end to end. Use it as the pattern for the Kubernetes use cases above: swap the input
(pod events / log tail instead of a CI log), the labels, the prefilter rules, and the
routed actions.

## Cluster access

When you wire the router to a real cluster:

- Run the agent with its own **ServiceAccount** and a namespaced **Role**/**RoleBinding**
  scoped to exactly the verbs it needs (e.g. `get`/`list`/`watch` on pods and events,
  `delete` on pods only in namespaces where auto-restart is allowed). Avoid
  `cluster-admin`.
- In shadow mode, grant **read-only** RBAC so a bug can't change the cluster.
- Keep destructive verbs (`delete` on PVCs, namespaces, deployments; `drain`; `cordon`)
  out of the agent's RBAC entirely. Those go through a human.

## Quickstart

```bash
cp .env.example .env     # set JEV_API_KEY, JEV_BASE_URL
pip install -r requirements.txt
python -m examples.ci_failure_triage --shadow   # dry-run, logs only
python -m examples.ci_failure_triage            # live routing
pytest
```

## Rollout strategy (do this, don't skip it)

1. **Shadow mode** for 1–2 weeks against the real cluster with read-only RBAC: log
   Jev's decision next to what on-call or your existing automation actually did.
   Don't act on it yet.
2. Compare agreement rate per label. Only automate the labels where Jev is
   consistently right and the blast radius of a wrong call is low (e.g. restarting a
   single pod in a non-critical namespace).
3. Expand automation gradually, namespace by namespace. Keep irreversible actions
   behind a human or a deterministic guardrail (see `agent/router.py::GUARDRAILS`)
   regardless of Jev's confidence.

## Known limits (bake these into your prefilter, not into Jev prompts)

- Don't ask Jev to count, do arithmetic, or compare dates as quantities ("restarted
  more than 5 times in 10 minutes", "replicas below desired"). Compute those from the
  Kubernetes API in code before calling Jev.
- Calibration holds in aggregate, not per-call. A single "92% confidence" answer can
  still be wrong, so don't gate irreversible cluster actions on a single call's
  confidence alone.
- English input performs best; other languages are unverified. Route those to the
  LLM-escalation path or a human.
