---
name: incident-demo-setup
description: Use when the user wants to set up, start, check the status of, run, or tear down the EKS incident-agent demo in this repo (Slack approval button, Jira ticket, Haiku analyzer/executor Lambdas, cluster.sh up/down). Finds which setup step they're on and walks them through the next one.
---

# Incident demo setup

The full checklist is in `doc/SETUP.md`. Read it first; this skill only adds how to work through it.

## 1. Find where the user is (read-only checks, run them, don't ask)

```bash
export AWS_PROFILE=will AWS_REGION=ap-south-1
aws lambda list-functions --query "Functions[?starts_with(FunctionName,'jev-incident-demo')].FunctionName" --output text
aws secretsmanager describe-secret --secret-id jev-incident-demo/config --query 'VersionIdsToStages' --output text \
  2>/dev/null || echo "config secret: missing"   # None/empty = no value yet -> scripts/put_config_secret.sh
grep -q 'not implemented yet' lambdas/analyzer/handler.py && echo "analyzer: placeholder"
grep -q 'not implemented yet' lambdas/executor/handler.py && echo "executor: placeholder"
(cd infra/terraform && ./cluster.sh status)
```

Map the results to a phase:
- No Lambdas → Phase 1/2 (steps 1–3)
- Lambdas but no secret values → step 4
- Secrets set → ask whether the Slack Interactivity URL is saved (step 5). Get it with `terraform output -raw slack_interactivity_url`.
- Handlers still placeholders → step 6
- Cluster ACTIVE → a session is running, and it costs about $0.20/h. Remind them about `./cluster.sh down`.

Tell the user which step they're on in one or two lines, then help with the next step only.

## 2. Rules
- Steps 1–2 (Slack app, Jira token, Bedrock model access) happen in web consoles. Give the user the clicks; you can't do them.
- All credentials are in ONE secret (`jev-incident-demo/config`: slack, jira, anthropic), built by `scripts/put_config_secret.sh` from local files. The model is Claude Haiku 5.5 on the Claude API, not Bedrock (the account's Bedrock quotas are 0).
- Never put Slack/Jira/Claude tokens in a command you run, a file you commit, or Terraform. The user runs `put-secret-value` themselves (suggest `! <command>`).
- `terraform apply`, `./cluster.sh up/down` and `terraform destroy` create or delete billable resources. Confirm before running them.
- After any session, check with `./cluster.sh status` that no EKS cluster is left running.
- For step 6, follow the checklist in `doc/SETUP.md` and the guardrails in `agent/router.py`. Keep the analyzer read-only and the executor limited to rolling back one Deployment.
- Once a step is done, tick it in `doc/SETUP.md` and update its Status line.
