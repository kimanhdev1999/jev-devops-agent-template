# Setup checklist: EKS incident agent with Slack approval

The steps to get the demo in [`incident-demo.md`](incident-demo.md) running, in order.
How the agent works end to end: [`sre-agent-flow.md`](sre-agent-flow.md).
Tick them off as you go.

**What it does:** a bad deploy of `demo-shop` on EKS → CloudWatch alarm → analyzer Lambda
(read-only) asks Claude Haiku 5.5 what went wrong → posts to Slack with an
**[Approve rollback]** button and opens a Jira ticket → a human clicks Approve →
executor Lambda rolls back that one Deployment.

**Defaults used below:** your AWS account, profile `will`, region `ap-south-1`,
resource prefix `jev-incident-demo`.

> **Status (2026-11-19): WORKING END TO END.**
> - Bad v2 deployed → alarm in about 90 s → Claude Haiku 5.5 (Claude API) diagnosed `bad_deploy` → Slack button + KAN-2 → human approved → rolled back in 1.8 s → alarm OK.
> - All credentials live in ONE secret, `jev-incident-demo/config`. Rebuild it with `scripts/put_config_secret.sh`
>   from `~/.slack_jev_demo`, `~/.jira_jev_demo`, `~/.atlassian_token_sre_will` and `~/.claude-api-token-will`.
> - Bedrock is NOT used: this account's Bedrock daily token quotas are 0. The manual steps below are kept for reference.

## Run a test session

```bash
export AWS_PROFILE=will AWS_REGION=ap-south-1
cd infra/terraform && ./cluster.sh up            # ~20 min (skip if it's already up)
helm upgrade demo-shop ../../charts/demo-shop -n demo --reuse-values --set version=v2 --set breakDb=true
aws logs tail /aws/lambda/jev-incident-demo-analyzer --follow   # Slack message in about 2 min
# click "Approve rollback" in Slack, then:
kubectl get pods -n demo -L app.kubernetes.io/version
./cluster.sh down                                 # always
```

## ✋ Your manual steps (everything else is automated)

**A. Slack app (about 5 min)**
1. Go to https://api.slack.com/apps → **Create New App** → **From a manifest** → pick your workspace.
2. Paste [`slack-app-manifest.yaml`](slack-app-manifest.yaml). It already has the scopes and the Interactivity URL. Click **Create**.
3. Click **Install to Workspace** → Allow.
4. Create a public channel, for example `#incidents`. You don't need to invite the bot.
5. Create `~/.slack_jev_demo` with these three lines:
   ```
   bot_token=xoxb-...      # OAuth & Permissions → Bot User OAuth Token
   signing_secret=...      # Basic Information → App Credentials → Signing Secret
   channel=incidents
   ```
6. Run `scripts/put_slack_secret.sh`, or ask Claude to. It checks the token, resolves the channel and stores the secret.

**B. Unlock Claude in Bedrock (about 2 min, one time per AWS account)**
1. Open the AWS console → **Amazon Bedrock** (region **Asia Pacific (Mumbai)**) → **Model catalog** → **Claude Haiku 5.5**.
2. Click **Submit use case details** (Anthropic's form), fill it in, and submit. Access usually starts within about 15 minutes.
3. Without this step the agent still runs. It just posts "needs a human" instead of a diagnosis.

---

## Phase 1: Accounts and access (one time, no AWS cost)

### 1. Slack app
- [ ] See ✋ A above. The manifest replaces the manual scope, Interactivity and invite steps.

### 2. Jira and Bedrock
- [x] Jira site: `https://<your-site>.atlassian.net`, project **KAN**, issue type **Bug**. The token is in `~/.atlassian_token_sre_will`.
- [x] API token tested: `curl -s -u "$JIRA_EMAIL:$JIRA_TOKEN" https://<your-site>.atlassian.net/rest/api/3/myself`.
- [ ] Bedrock: see ✋ B above. Check it with:
  `aws bedrock-runtime converse --model-id global.anthropic.claude-haiku-5-5 --messages '[{"role":"user","content":[{"text":"hi"}]}]'`
- [x] Kubernetes 1.37 is in standard support in ap-south-1.
- [ ] Optional: add your SSO/console role ARN to `admin_principal_arns` in `infra/terraform/terraform.tfvars` so you can run `kubectl`.

## Phase 2: Always-on AWS layer (about $0/h, stays up all week)

### 3. Terraform apply without the cluster
```bash
export AWS_PROFILE=will AWS_REGION=ap-south-1
cd infra/terraform
# backend.hcl and terraform.tfvars already exist locally (gitignored);
# otherwise copy them from the *.example files.
terraform init -backend-config=backend.hcl
terraform apply -var enable_cluster=false        # ~2 min
```
- [x] Apply succeeded. You should see `jev-incident-demo-analyzer` and `-executor` Lambdas, two secrets, the alarm and the log group.

### 4. Put the secret values in
The values go straight into Secrets Manager, never into Terraform state.
```bash
aws secretsmanager put-secret-value --secret-id jev-incident-demo/slack \
  --secret-string '{"bot_token":"xoxb-...","signing_secret":"...","channel_id":"C..."}'

aws secretsmanager put-secret-value --secret-id jev-incident-demo/jira \
  --secret-string '{"base_url":"https://<your-site>.atlassian.net","email":"...","api_token":"...","project_key":"KAN"}'
```
- [ ] Slack secret set (✋ A, `scripts/put_slack_secret.sh`).
- [x] Jira secret set (KAN, issue type Bug).

> Tip: put a space before the command, or use `--secret-string file://slack.json`, so the token
> stays out of your shell history. Delete the file afterwards.

### 5. Connect the Slack button to the executor
```bash
terraform output -raw slack_interactivity_url
```
- [x] Done by the manifest: Slack app → **Interactivity & Shortcuts** → On → paste the URL as **Request URL** → Save.
  - The URL stays the same all week; `cluster.sh up/down` doesn't change it.

## Phase 3: Write the agent code (the missing part)

### 6. Implement the two Lambdas
**Analyzer**, in `lambdas/analyzer/handler.py`. It is read-only and triggered by the alarm through EventBridge.
- [x] Collect evidence in code:
  - a Logs Insights query on `APP_LOG_GROUP` for the alarm window
  - `GetMetricData` for `DbConnectionErrors` and `Http5xx`
  - the Deployment rollout history. Set `new_revision_in_window` when a new revision appeared just before the alarm.
- [x] Mask PII (emails, IPs, tokens, long digit runs) before anything leaves the function.
- [x] Call `agent.incident.decide(evidence_text)`. If it returns `None`, hold for a human.
- [x] Call `agent.router.route_incident(...)`, which gives `offer_rollback` / `ticket_only` / `hold_for_human`.
- [x] Post the summary to Slack with `chat.postMessage`. Add the `approve_rollback` button only for `offer_rollback`.
- [x] Create the Jira ticket and put its key in the button `value` so the executor can comment on it.

**Executor**, in `lambdas/executor/handler.py`. It runs only from the Slack button, through the Function URL.
- [x] Verify `X-Slack-Signature` (HMAC-SHA256 with the signing secret). Reject timestamps older than 5 minutes with a 401.
- [x] Accept only `action_id == "approve_rollback"` for `APP_NAMESPACE` / `APP_DEPLOYMENT`.
- [x] Roll back: patch the Deployment template back to the previous ReplicaSet's template (what `kubectl rollout undo` does).
- [x] Update the Slack message ("rolled back by @user") and comment on the Jira ticket.
- [x] Reply to Slack within 3 seconds. The rollback patch is fast, so a direct response is fine.

**EKS auth from Lambda:** build a bearer token with a presigned STS `GetCallerIdentity` request (header `x-k8s-aws-id`). The cluster endpoint and CA come from `eks:DescribeCluster`. The access entries and RBAC already exist in Terraform.

**Packaging:** `scripts/build_lambdas.sh` builds `infra/terraform/.build/src/{analyzer,executor}` (Linux wheels for Python 3.12). Run it before any `terraform apply`; `cluster.sh up` runs it for you.
- [x] Unit tests pass (`pytest`, 27 tests).
- [x] Lambdas deployed. A test invoke created KAN-1.

## Phase 4: Run a demo session (about $0.20/h while the cluster is up)

### 7. Each session
```bash
cd infra/terraform
./cluster.sh up          # ~20 min: EKS + 2× t3.small + demo-shop v1, then lists the pods

# break it: a "bad release"
helm upgrade demo-shop ../../charts/demo-shop -n demo --reuse-values \
  --set version=v2 --set breakDb=true
```
- [ ] Within about 1–2 min the alarm `jev-incident-demo-demo-shop-db-errors` goes to ALARM.
- [ ] A message shows up in the Slack channel and a Jira ticket is created.
- [ ] Click **Approve rollback**. demo-shop goes back to v1, the errors stop and the alarm returns to OK.
- [ ] **Always finish with:**
```bash
./cluster.sh down        # ~10 min
./cluster.sh status      # should print "not running (no EKS charges)"
```

### 8. After the last session
```bash
./cluster.sh down && terraform destroy -var enable_cluster=false
aws logs describe-log-groups --log-group-name-prefix /aws/containerinsights/jev-incident-demo \
  --query 'logGroups[].logGroupName' --output text | xargs -n1 aws logs delete-log-group --log-group-name
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| No Slack message | Analyzer logs: `aws logs tail /aws/lambda/jev-incident-demo-analyzer --follow`. Is the bot in the channel? Is the scope `chat:write`? |
| Slack shows an error when you click the button | Executor logs. Signature check: use the raw body, and the signing secret, not the bot token. |
| Bedrock 4xx | Model access enabled in ap-south-1? Account verification done? IAM `bedrock-mantle:CreateInference`? |
| Lambda gets 401/403 from EKS | Token format (`k8s-aws-v1.` prefix, `x-k8s-aws-id` header), access entry present, cluster up |
| Alarm never fires | Is Fluent Bit shipping to `/aws/containerinsights/jev-incident-demo/application`? Is `breakDb=true` applied? |
| Pods stuck in Pending | Set `node_instance_type = "t3.medium"` in tfvars |
