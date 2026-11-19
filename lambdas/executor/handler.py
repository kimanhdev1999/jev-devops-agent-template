"""Executor Lambda (Slack button -> rollback) - PLACEHOLDER.

It deliberately does nothing until the real logic exists. Planned flow:
  1. Verify X-Slack-Signature (HMAC-SHA256 with the signing secret) and reject
     timestamps older than 5 minutes. Reject everything else with 401.
  2. Accept only action_id == "approve_rollback" for APP_NAMESPACE/APP_DEPLOYMENT.
  3. Revert the Deployment to its previous ReplicaSet template (= kubectl rollout undo).
  4. Update the Slack message and comment on the Jira ticket with who approved it.
"""

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    logger.info("executor invoked (not implemented yet); refusing to act")
    return {"statusCode": 501, "body": "executor not implemented yet"}
