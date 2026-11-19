# SRE incident agent: demo recording plan

A plan for a **10–12 minute recorded walkthrough**, plus optional deep-dive scenes. It follows the
run verified on 2026-11-19 (KAN-2). For presenting in front of an audience, see
[`DEMO_LIVE_PLAN.md`](DEMO_LIVE_PLAN.md).

There are two ways to make the recording:
- **Option A: you record it** (sections 0–7). Best quality: your voice, your pacing, and a real human click.
- **Option B: Claude records it unattended** (section 8). Faster for you, but rougher: a synthetic voice and a fixed pace.

**The story in one line:** a bad release breaks checkout. The agent notices, gathers the evidence and
diagnoses the problem, opens a ticket and asks for permission. A human clicks once, and the service
recovers. The AI never touches the cluster itself.

**Four points every viewer should take away** (repeat them at the start and the end):
1. The model only **classifies**. It picks from a fixed list and never writes commands.
2. **Code decides.** A rollback is offered only when the model's diagnosis *and* a fact checked in code agree.
3. **A human approves.** Nothing changes without a click in Slack.
4. **The identity that thinks is not the identity that writes.** The analyzer is read-only, and the executor can roll back one Deployment and nothing else.

---

## 0. Time budget

| Phase | Real time | In the final video |
|---|---|---|
| `./cluster.sh up` (do this before recording) | ~20 min | 0 |
| Pre-flight checks | ~10 min | 0 |
| Recording the main take | ~20 min (includes ~8 min waiting for the alarm to clear) | 10–12 min after cuts |
| Optional deep-dive scenes | ~10 min | 3–5 min |
| `./cluster.sh down` | ~10 min | 0 |

Cost: about $0.20/h while the cluster is up, so the whole session costs **about $0.50–1.00**.

---

## 1. Pre-production (T-45 min)

### 1.1 Start the cluster
```bash
export AWS_PROFILE=will AWS_REGION=ap-south-1
cd ~/BelleGitRepos/jev-devops-agent-template/infra/terraform
./cluster.sh up            # ~20 min; ends by listing the demo-shop v1 pods
```

### 1.2 Pre-flight checklist (all must pass before you hit Record)
```bash
kubectl get pods -n demo -L app.kubernetes.io/version          # 2/2 Running, version v1
aws cloudwatch describe-alarms --alarm-names jev-incident-demo-demo-shop-db-errors \
  --query 'MetricAlarms[0].StateValue' --output text            # OK  (if INSUFFICIENT_DATA, wait 2–3 min)
helm history demo-shop -n demo                                  # note the current revision number
terraform output -raw slack_interactivity_url                   # keep it for scene 9 (don't show it on screen)
```
- [ ] The `sre_agent` bot is in the demo Slack channel. Old test messages are deleted, or you've switched to a fresh channel.
- [ ] Jira KAN board is open. Old test tickets (KAN-2 …) are closed or filtered out, so the new ticket is easy to spot.
- [ ] `.venv/bin/python -m pytest tests -q` passes (27 tests). You'll use this in scene 10.
- [ ] Notifications are off (macOS Focus mode, Slack DND for other workspaces).
- [ ] Nothing secret is visible: no `cat` of `~/.atlassian_token_*`, `~/.claude-api-token-*` or `~/.slack_jev_demo`, and no `aws secretsmanager get-secret-value`.
       The AWS account ID appears in ARNs, so blur it in editing if needed.

### 1.3 Screen layout
Record at 1920×1080. If you're on a Retina screen, scale the display down to "looks like 1920×1080".

| Window | Content | Prepared tabs / panes |
|---|---|---|
| **Terminal** (font 18–20 pt, dark theme) | 3 panes or tabs | ① commands ② `kubectl get pods -n demo -L app.kubernetes.io/version -w` ③ `aws logs tail /aws/lambda/jev-incident-demo-analyzer --follow --format short` |
| **Browser tab 1** | `doc/architecture.png` or the mermaid diagram in `doc/sre-agent-flow.md` | |
| **Browser tab 2** | CloudWatch ▸ Alarms ▸ `jev-incident-demo-demo-shop-db-errors` (graph set to 1 h) | |
| **Browser tab 3** | Slack demo channel | |
| **Browser tab 4** | Jira KAN board | |
| **Editor** (VS Code) | `agent/router.py`, `agent/incident.py` (schema), `lambdas/executor/handler.py`, `infra/terraform/k8s.tf` (RBAC) | |

### 1.4 Recording tool
- I don't have a screen recorder installed besides macOS's built-in one, so use **Cmd+Shift+5 ▸ Record Entire Screen**. Under Options, pick your microphone and "Show Mouse Clicks".
- Alternatives: QuickTime (File ▸ New Screen Recording), OBS (free, `brew install --cask obs`) if you want a webcam overlay, or Loom.
- **Record each scene as a separate clip** (stop and start between scenes). Retakes are cheaper and the waits get cut naturally.

---

## 2. Shot list

Times are for the edited video. *Narration* is a suggestion, so say it in your own words.

### Scene 1: Hook (0:00–0:45)
- **Screen:** Slack channel with the final result from a rehearsal: a diagnosis plus "✅ Rolled back … approved by @you". Or just you on camera.
- **Narration:** "A bad deploy just broke checkout at 3 a.m. Health checks are green, so Kubernetes thinks everything is fine.
  In the next ten minutes you'll see an AI agent find the problem, open a ticket, and fix it, but only after a human says yes."
- **Tip:** record this scene **last**, once you have the real result to show.

### Scene 2: Architecture (0:45–2:15)
- **Screen:** browser tab 1, the architecture diagram. Point at each box as you go.
- **Walk the path:** demo-shop on EKS → logs to CloudWatch → metric filter → alarm → EventBridge → **analyzer Lambda** (read-only) → Claude Haiku 5.5 → Jira + Slack → human → **executor Lambda** (rollback only) → EKS.
- **Say the four takeaways here.**
- **Point out:** there's no long-running agent server. Each alarm starts one Lambda run, and there's one model call per incident.

### Scene 3: The healthy baseline (2:15–3:00)
- **Screen:** terminal pane ② (pods v1, Running), then the CloudWatch alarm tab showing **OK** with a flat error graph.
```bash
kubectl logs -n demo deploy/demo-shop --tail=5          # status=200 order lines
```
- **Narration:** "This is demo-shop v1, a small service placing fake orders. Every order logs a line. Errors are at zero and the alarm is OK."

### Scene 4: Ship the bad release (3:00–4:00)
- **Screen:** terminal pane ①, with pane ② visible beside it.
```bash
helm upgrade demo-shop ../../charts/demo-shop -n demo --reuse-values \
  --set version=v2 --set breakDb=true
```
- **Show:** pane ② swaps the pods to **v2**, and they come up **Running and Ready**.
```bash
kubectl logs -n demo deploy/demo-shop --tail=5          # ERROR db connection refused … status=500
```
- **Narration:** "v2 has a broken database setting. Notice the rollout *succeeded*: liveness and readiness checks pass, so Kubernetes is happy. Only the logs show the problem. This is the kind of incident that pages people."
- **Note the wall-clock time.** You'll quote it in scene 8.

### Scene 5: Detection (4:00–5:00) *(about 90 s of real waiting; cut it down)*
- **Screen:** CloudWatch alarm tab. Refresh until the graph jumps (~100 errors/min) and the state turns **ALARM**.
- **Narration:** "A metric filter counts 'db connection refused' lines. At 5 or more per minute the alarm fires, and EventBridge invokes the analyzer."
- **Editing:** show the first refresh, jump-cut to ALARM, and add a "+90 s" caption.

### Scene 6: The analyzer at work (5:00–6:30)
- **Screen:** terminal pane ③ (analyzer logs streaming; the run takes about 10 s).
- **Walk through what it does, in order** (you can overlay the table from `doc/sre-agent-flow.md` §2 ②):
  1. Collects evidence **in code**: Logs Insights counts per version, the latest error lines, errors per minute, and the rollout history from the EKS API.
  2. Computes the deterministic fact `new_revision_in_window`: a new ReplicaSet appeared just before the alarm.
  3. **Masks** emails, IPs, tokens and long numbers (`agent/masking.py`).
  4. Makes **one** Claude call and gets back a **typed** answer.
- **Cut to the editor, `agent/incident.py`:** show the schema. `root_cause` can only be `bad_deploy · db_outage · oom · image_pull · traffic_spike · unknown`. There's a severity, a `rollback_likely_fixes` flag, a confidence and a summary. "It can't invent an action. There's no field to put one in."
- **Cut to `agent/router.py` (`route_incident`):** show the guardrail table. A rollback is offered only if `bad_deploy`, **and** code saw a new revision, **and** the model says a rollback fixes it, **and** confidence ≥ 0.75. Otherwise the result is `ticket_only` or `hold_for_human`.

### Scene 7: Slack and Jira (6:30–8:00)
- **Screen:** Slack tab. Read the message aloud:
  root cause **bad_deploy**, severity, confidence, evidence bullets, the **Routing:** line (why it offers a rollback), the Jira link, and the red **Approve rollback to revision N** button.
- **Click the Jira link** → the new KAN Bug: summary, routing reason, full masked evidence, labels `incident-agent` and `demo-shop`.
- **Narration:** "Within seconds of the alarm, on-call has a diagnosis, the evidence, and a ticket. Up to this point the agent has changed nothing. It doesn't have the permissions to."

### Scene 8: Human approval and rollback (8:00–9:30)
- **Screen:** Slack, with terminal pane ② visible.
- Click **Approve rollback** → the confirmation dialog appears ("are you sure?") → click **Roll back**.
- **Show at the same time:** pane ② swaps the pods back to **v1** (the executor runs in about 2 s). The Slack button is replaced by "✅ Rolled back … approved by @you".
- **Jira tab:** the new comment "Rolled back … approved by …".
```bash
kubectl logs -n demo deploy/demo-shop --tail=5          # status=200 again
```
- **Narration:** "That click went to a *different* Lambda. It checked Slack's signature, checked that the button targets demo/demo-shop, checked that the Deployment hasn't changed since, and patched it back. That's the same thing `kubectl rollout undo` does."
- **Quote the timeline:** bad deploy → alarm → diagnosis → fix. On the verified run that was +91 s to the alarm, +11 s to the diagnosis, and a 1.8 s rollback.

### Scene 9: Recovery (9:30–10:15) *(about 8 min of real waiting; cut it down)*
- **Screen:** CloudWatch alarm graph: the error line drops to 0, and the state returns to **OK**.
- **Editing:** use a jump-cut with a "+8 min" caption, or record it as a separate clip later.

### Scene 10: Why it's safe (10:15–11:30)
Pick 2 or 3 of these (all of them are in the deep-dive section if you want a longer cut):
- **Least privilege, shown in code:** `infra/terraform/k8s.tf`. The `rollback-executor` Role allows `get`/`patch` on **`deployments/demo-shop` only**, and the analyzer has view access to namespace `demo` only.
- **A forged click is rejected (live):**
  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' -X POST "$(terraform output -raw slack_interactivity_url)" -d 'payload={}'
  # → 401: no valid Slack signature, nothing happens
  ```
- **A double click is safe:** click Approve again (or use a second user) → "Nothing done". The executor is idempotent because it acts only if the Deployment is still on `from_rev`.
- **Tests:** `.venv/bin/python -m pytest tests -q` → 27 passed (router, schema, masking, signature, rollback).

### Scene 11: Wrap-up (11:30–12:00)
- **Screen:** the architecture diagram again, or you on camera.
- Repeat the four takeaways, then mention the next steps: more scenarios (OOM, image pull → `ticket_only`), **shadow mode** against real incidents before any automation, and a later swap of the Claude call for Jev (`decide()` keeps the same `IncidentDecision` shape).

---

## 3. Optional deep-dive scenes (for a longer, technical cut)

| Scene | What to show | How |
|---|---|---|
| A. "No button" path | The router refuses to offer a rollback when there was no recent deploy | After recovery and the alarm returning to OK, run `aws cloudwatch set-alarm-state --alarm-name jev-incident-demo-demo-shop-db-errors --state-value ALARM --state-reason "demo: manual trigger"`. The analyzer runs, finds no new revision and no errors → **no button**, `ticket_only` or `hold_for_human`. Note: this creates a real KAN ticket. |
| B. Masking | PII never reaches Claude, Jira or Slack | `agent/masking.py` plus the masked evidence in the Jira ticket (fake emails/IPs show as placeholders) |
| C. Failure is safe | If Claude is unreachable, the decision is `None` → `hold_for_human` | Walk through the code in `agent/incident.py`. Don't break the real key during the recording. |
| D. Permissions in AWS | Analyzer vs executor IAM roles | `infra/terraform/iam.tf`, or the IAM console for both roles side by side |
| E. Cost | ~$0.20/h cluster, ~$0 always-on layer, pennies per incident | `./cluster.sh status` + the cost section of `doc/incident-demo.md` |

---

## 4. Retakes and reset

To redo scenes 4–9:
1. Wait until the alarm is back to **OK**. The analyzer fires only on a state *change* to ALARM.
2. Re-run the `helm upgrade … --set version=v2 --set breakDb=true` from scene 4, then check with `kubectl get pods -n demo -L app.kubernetes.io/version` that the pods are on **v2** again (the executor's rollback patched the Deployment outside Helm).
3. Each take creates a new KAN ticket. Close the extra ones afterwards.

## 5. If something goes wrong on camera

| Symptom | Quick fix |
|---|---|
| No Slack message after ~2 min | Pane ③: analyzer error? Is the bot in the channel? (`/invite @sre_agent`) |
| Message says "needs a human" | The Claude call failed (key/quota). Check the analyzer logs for `Claude call failed`. |
| No button | Read the "Routing:" line. Usually the alarm fired too long after the deploy (more than 20 min). Redo scene 4. |
| Clicking the button shows a Slack error | `aws logs tail /aws/lambda/jev-incident-demo-executor`. A 401 means the signing secret is wrong. |
| Alarm stuck in INSUFFICIENT_DATA | Fluent Bit hasn't shipped logs yet. Wait 2–3 min after `cluster up`. |

**Plan B:** do one full rehearsal take first and keep it. If the live take goes wrong, edit in the rehearsal footage.

## 6. Teardown (don't skip, since the cluster bills hourly)
```bash
./cluster.sh down          # ~10 min
./cluster.sh status        # "not running (no EKS charges)"
```

## 7. Post-production
- Cut the waits (scenes 5 and 9) and add "+90 s" / "+8 min" captions so the real timeline stays honest.
- Zoom in (2×) on the Slack message, the schema in `incident.py`, and the router table. They're unreadable at full screen.
- Add lower-third labels: "Analyzer (read-only)", "Executor (rollback only)", "Human approval".
- Blur the AWS account ID and the Function URL wherever they appear.
- Chapters for YouTube/Loom: Architecture · Bad deploy · Detection · Diagnosis · Approval · Recovery · Safety.

---

## 8. Option B: Claude records it unattended

Claude Code drives the terminal and your Chrome while macOS records the screen. It then adds narration and captions,
cuts the waits, and gives you an MP4 rough cut. You can re-voice it later if you want.

### What it uses
| Need | Tool | Status on this Mac |
|---|---|---|
| Screen capture | `screencapture -v` (built into macOS) | available. The terminal app needs **System Settings ▸ Privacy & Security ▸ Screen Recording** |
| Browser steps (alarm page, Slack, Jira) | Claude in Chrome extension | must be installed and allowed on `console.aws.amazon.com`, `app.slack.com` and `ingen-44599418.atlassian.net` |
| Narration | `say -v Samantha -o scene.aiff` (built into macOS) | available |
| Cutting, joining, captions, audio | `ffmpeg` | not installed. `brew install ffmpeg` |
| Terminal-only close-ups (optional) | `vhs` (scripted terminal video) | not installed. `brew install vhs` |

### The approval click
This is the one step that must stay honest, because "a human approves" is the point of the demo. The choices:
1. **Recommended:** Claude pauses at scene 8 and sends you a notification. You click **Approve** yourself (even from your phone),
   then Claude carries on. The Slack message shows your name.
2. Claude clicks the button in your Chrome on your behalf. It still goes through Slack's signed request, but the approval is really
   Claude's, so say so in the captions.

Claude will **not** fake the click by signing a request with the secret from Secrets Manager. That would skip the very control the
demo is about.

### How the run works
1. You: grant Screen Recording permission, install `ffmpeg`, log into AWS console, Slack and Jira in Chrome. Then **leave the
   Mac alone** for about 35 minutes (any mouse movement ends up in the video).
2. Claude: `./cluster.sh up` and the pre-flight checks (section 1.2).
3. Claude: records scenes 3–10 as separate clips with `screencapture -v -V <seconds>`, running the same commands and
   opening the same pages as in section 2.
4. Claude: writes the narration from section 2, generates it with `say`, and joins clips plus audio with `ffmpeg`. It adds
   "+90 s" / "+8 min" captions over the cuts and zooms on the Slack message, schema and router.
5. Claude: `./cluster.sh down` and `./cluster.sh status`.
6. You: watch the MP4 (saved under `doc/video/`). Re-record any scene or re-voice it yourself.

### Limits
- A synthetic voice and fixed timing. It's good for an internal walkthrough, but weaker for a pitch or an external audience.
- The editor scenes (schema, router, RBAC) are shown by opening the files in an editor window. There's no live pointing, only zoom and captions.
- Real side effects: one or two KAN tickets and Slack messages, and about $0.20/h while the cluster is up.
