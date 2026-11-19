# SRE incident agent: live demo plan

A run of show for presenting the agent **live** (in a room or over Zoom/Teams) in a **20-minute slot**:
about 15 minutes of demo plus 5 minutes of Q&A. For a recorded video, see
[`DEMO_RECORDING_PLAN.md`](DEMO_RECORDING_PLAN.md).

**How a live demo differs from a recording:** you can't cut the waits. Waiting for the alarm takes about 90 s and
recovery takes about 8 min. So the plan **triggers the incident early and explains while the system works**. It also
has a fallback for every step, because a live audience doesn't forgive a stuck screen.

**Four points the audience should take away** (say them at the start and the end):
1. The model only **classifies**. It picks from a fixed list and never writes commands.
2. **Code decides.** A rollback is offered only when the model's diagnosis *and* a fact checked in code agree.
3. **A human approves.** Nothing changes without a click in Slack.
4. **The identity that thinks is not the identity that writes.** The analyzer is read-only, and the executor can roll back one Deployment.

---

## 1. Roles

| Role | Who | Job |
|---|---|---|
| Presenter | you | talks and drives the screen |
| Approver (recommended) | a colleague **in the audience** who is a member of the Slack channel | clicks **Approve rollback** when asked. It proves a separate human made the decision, and the Slack message records their name. |
| Backup operator (optional) | a second person or a second laptop | watches the analyzer and executor logs and tells you quietly if something fails |

---

## 2. Timeline before the demo

| When | What | Done when |
|---|---|---|
| Day before | **Two full dry runs** (sections 4 and 6), timed | both runs finish within 15 min with a button in Slack |
| Day before | Make the backup video (follow `DEMO_RECORDING_PLAN.md`) and save rehearsal screenshots: Slack message, Jira ticket, alarm graph | file opens offline |
| T-60 min | `./cluster.sh up` (~20 min) | demo-shop v1 pods listed |
| T-30 min | Pre-flight checks (section 3) | all boxes ticked |
| T-20 min | **Last rehearsal must be finished, and the alarm must be OK.** The analyzer fires only on a *change* to ALARM. | `describe-alarms` → `OK` |
| T-10 min | Screen layout, Focus mode on, share-screen test | audience can read the 20-pt terminal |
| T-0 | Start | |

```bash
export AWS_PROFILE=will AWS_REGION=ap-south-1
cd ~/BelleGitRepos/jev-devops-agent-template/infra/terraform
./cluster.sh up
```

---

## 3. Pre-flight checks (T-30)

```bash
kubectl get pods -n demo -L app.kubernetes.io/version            # 2/2 Running, v1
aws cloudwatch describe-alarms --alarm-names jev-incident-demo-demo-shop-db-errors \
  --query 'MetricAlarms[0].StateValue' --output text              # OK
kubectl logs -n demo deploy/demo-shop --tail=3                    # status=200 lines
```
- [ ] The `sre_agent` bot and the **approver** are both in the Slack channel. The channel is clean, or you've created a fresh one for the day.
- [ ] Jira KAN board filtered to open tickets. Old test tickets are closed.
- [ ] Browser: logged into the AWS console (alarm page), Slack and Jira. Tabs are in the order of section 5.
- [ ] Terminal: 3 panes, 20 pt font (section 5). The `helm upgrade` command is typed but **not run** in pane ①.
- [ ] Notifications off (macOS Focus, Slack DND for other workspaces, Mail and Teams closed).
- [ ] Backup video and screenshots are open in a hidden window.
- [ ] Nothing secret is on screen: no token files, no `get-secret-value`, no `terraform output` of the Function URL.
- [ ] Wired network or a phone hotspot is ready as a backup.

---

## 4. Run of show (real time)

| Clock | Segment | On screen | What you do / say |
|---|---|---|---|
| **0:00** | Hook | slide or you | "A bad deploy breaks checkout at 3 a.m. Health checks are green. Let's watch an AI agent handle it, and see why it can't break anything itself." |
| **1:00** | Baseline | terminal panes ①② + alarm tab | v1 pods Running. `kubectl logs … --tail=3` → `status=200`. Alarm **OK**, flat graph. |
| **2:00** | **Ship the bad release** | terminal ① + ② | Run the prepared `helm upgrade … --set version=v2 --set breakDb=true`. Pods roll to **v2, Running and Ready**. `kubectl logs` → `ERROR db connection refused`. "Kubernetes thinks this rollout succeeded." **Say the time out loud.** |
| **3:00** | Architecture *(fills the ~90 s wait for the alarm)* | architecture diagram | Walk the path: logs → metric filter → alarm → EventBridge → **analyzer** (read-only) → Claude → Jira + Slack → human → **executor** (rollback only). Say the four takeaways. Glance at the alarm tab at the end. |
| **~4:30** | Alarm fires | alarm tab | State **ALARM**, graph at ~100 errors/min. "EventBridge has just started the analyzer." Switch to pane ③: analyzer logs scroll for ~10 s. |
| **5:00** | Diagnosis | Slack | Read the message: **bad_deploy**, severity, confidence, evidence, the **Routing:** line, the red **Approve rollback** button. "About 10 seconds after the alarm. Nothing has changed in the cluster yet." |
| **6:00** | Ticket | Jira | Open the new KAN Bug: summary, routing reason, masked evidence. |
| **7:00** | Why there's a button | editor: `agent/incident.py`, then `agent/router.py` | The schema has a fixed list of root causes and no field for commands. The router offers a rollback only if `bad_deploy` **and** code saw a new revision **and** the model says rollback fixes it **and** confidence ≥ 0.75. |
| **9:00** | **Human approval** | Slack + terminal ② side by side | "<Approver>, could you approve it?" They click **Approve** → **Roll back**. Pods swap to **v1** (~2 s). Slack shows "✅ Rolled back … approved by @approver". Jira gets a comment. `kubectl logs` → `status=200`. |
| **10:00** | Why it's safe *(fills the ~8 min until the alarm clears)* | editor + terminal | ① `infra/terraform/k8s.tf`: executor can `get`/`patch` **only `deployments/demo-shop`**. ② The approver clicks Approve **again** → "Nothing done" (idempotent). ③ A forged request (prepared command, URL hidden) → **401**. ④ `.venv/bin/python -m pytest tests -q` → 27 passed. ⑤ Masking: point at the placeholders in the Jira evidence. |
| **13:00** | Limits and next steps | slide | One scenario so far. OOM, image pull and DB outage map to `ticket_only`. Next: shadow mode against real incidents before any automation, then Jev in place of the Claude call. |
| **14:00** | Recovery check | alarm tab | Graph back at 0. If the state is already **OK**, show it. If not: "it needs a few clean minutes, and we'll check again after questions." |
| **15:00** | Q&A | | section 7 |
| **~19:00** | Close | alarm tab | Show **OK**, then repeat the four takeaways. |

**The forged-request command** (prepare it in pane ① before the demo so the URL never shows on screen):
```bash
URL=$(terraform output -raw slack_interactivity_url); clear
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$URL" -d 'payload={}'     # → 401
```

---

## 5. Screen layout

Share **one** browser window and **one** terminal, not the whole desktop, so private windows never appear.

| Window | Contents |
|---|---|
| Terminal (20 pt) | ① commands ② `kubectl get pods -n demo -L app.kubernetes.io/version -w` ③ `aws logs tail /aws/lambda/jev-incident-demo-analyzer --follow --format short` |
| Browser tabs, in order | 1 architecture diagram · 2 CloudWatch alarm (1 h graph, auto-refresh 10 s) · 3 Slack channel · 4 Jira KAN board |
| Editor | `agent/incident.py`, `agent/router.py`, `infra/terraform/k8s.tf`, each scrolled to the right spot beforehand |

---

## 6. When something goes wrong live

Rule: **keep talking, switch to the fallback within 60 seconds, and fix it after the demo.**

| Symptom | Say | Do |
|---|---|---|
| Pods don't roll to v2 | "Helm is being slow, so let me show you what it looks like." | Check `helm history demo-shop -n demo`. If it's stuck, switch to the backup video from scene 4. |
| Alarm not in ALARM after 3 min | "CloudWatch evaluates once a minute, so let's give it a moment." | Check `kubectl logs` for ERROR lines. Last resort: `aws cloudwatch set-alarm-state --alarm-name jev-incident-demo-demo-shop-db-errors --state-value ALARM --state-reason demo`. The analyzer still sees the real bad revision and errors. |
| No Slack message 1 min after ALARM | "While that comes through, here's the message from this morning's run." | Show the rehearsal screenshot. Check pane ③ for errors (`Claude call failed`, Slack `not_in_channel`). |
| Message has **no button** | "This is the guardrail working. It isn't sure enough, so it hands over to a human." Turn it into a teaching moment. | Read the Routing line aloud. Roll back by hand: `kubectl rollout undo deploy/demo-shop -n demo`. |
| Approve shows an error in Slack | "Signature checks are strict. Let me show the result from rehearsal." | Show the screenshot. Roll back by hand with `kubectl rollout undo`. Check the executor logs afterwards. |
| Network or VPN dies | | Switch to the backup video and narrate over it. |

---

## 7. Q&A: likely questions

| Question | Answer |
|---|---|
| What if the model is wrong? | It can only pick a label. A wrong label gives a wrong ticket, not a wrong action. A rollback also needs a fact checked in code (a new revision just before the alarm), plus a human click. |
| Can it hallucinate a command? | No. The output is schema-validated and there's no field for commands. The executor only runs a fixed rollback of one Deployment. |
| What data goes to Claude? | Masked log lines, metrics and rollout metadata. Emails, IPs, tokens and long numbers are removed first (`agent/masking.py`). |
| Why the Claude API and not Bedrock? | This account's Bedrock daily token quotas are 0 (a new-account restriction). The code keeps the same decision shape, so switching later is a config change plus a Support case. |
| How much does it cost? | About $0.20/h for the demo cluster, ~$0 for the always-on part, and a fraction of a cent per incident for the model call. |
| How fast is it? | In the verified run: alarm 91 s after the deploy, diagnosis 11 s later, rollback in 1.8 s after approval. |
| Why Lambda and not something in the cluster? | No servers to run, and the agent keeps working even if the cluster itself is unhealthy. |
| Can it fix other incidents? | It recognizes OOM, image pull, DB outage and traffic spikes, but those only open a ticket. Each new automatic action needs its own narrow executor permission and a guardrail. |
| Is this production-ready? | No. Public subnets, a public EKS endpoint and no shadow-mode period. The next step is 1–2 weeks of shadow mode against real incidents. |

---

## 8. After the demo
```bash
./cluster.sh down          # ~10 min, stops EKS charges
./cluster.sh status        # "not running (no EKS charges)"
```
Close the demo KAN tickets and post the recording or slides link in the channel.
