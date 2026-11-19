"""Analyzer Lambda (read-only) - PLACEHOLDER so `terraform apply` has a package.

Planned flow (next step, not implemented yet):
  1. Evidence in code: Logs Insights query on APP_LOG_GROUP for the alarm window,
     GetMetricData for DbConnectionErrors / Http5xx, Deployment rollout history.
  2. Mask PII (emails, IPs, tokens, long digit runs) before anything leaves AWS.
  3. agent.incident.decide(): one Haiku 5.5 call (Bedrock Mantle, structured
     output) -> root cause, severity, rollback-fixes-it, confidence, summary.
  4. agent.router.route_incident(): button only if the model says bad_deploy AND
     code saw a recent rollout. Then Slack message + Jira ticket.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    detail = event.get("detail", {})
    logger.info(
        "alarm=%s state=%s (analyzer not implemented yet)",
        detail.get("alarmName"),
        detail.get("state", {}).get("value"),
    )
    logger.info(json.dumps(event))
    return {"status": "placeholder"}
