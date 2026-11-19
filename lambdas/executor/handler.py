"""Executor Lambda: runs ONLY on a signed Slack button click (public Function URL).

  1. Verify X-Slack-Signature (HMAC-SHA256, signing secret), reject requests older than 5 min.
  2. Accept only action_id == "approve_rollback" for APP_NAMESPACE/APP_DEPLOYMENT.
  3. Idempotent rollback: act only if the Deployment is still on the revision the
     analyzer saw; then copy the previous ReplicaSet's pod template back
     (= kubectl rollout undo --to-revision). Double-clicks become no-ops.
  4. Update the Slack message and comment on the Jira ticket.

Its Kubernetes identity can only get/patch this one Deployment and read ReplicaSets.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse

from agent.integrations import Kube, jira_comment, revision_of, secret, slack_respond

logger = logging.getLogger()
logger.setLevel(logging.INFO)

NS = os.environ.get("APP_NAMESPACE", "demo")
DEPLOY = os.environ.get("APP_DEPLOYMENT", "demo-shop")
MAX_AGE_SECONDS = 300


def _reply(status: int, text: str = "") -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "text/plain"}, "body": text}


def verify_slack_signature(signing_secret: str, headers: dict, raw_body: str, now: float | None = None) -> bool:
    ts = headers.get("x-slack-request-timestamp", "")
    sig = headers.get("x-slack-signature", "")
    if not ts.isdigit() or not sig:
        return False
    if abs((now or time.time()) - int(ts)) > MAX_AGE_SECONDS:
        return False
    base = f"v0:{ts}:{raw_body}".encode()
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def rollback(kube: Kube, from_rev: int, to_rev: int) -> str:
    """Returns a human-readable result. Raises on API errors."""
    dep = kube.get_deployment(NS, DEPLOY)
    current = revision_of(dep)
    if current != from_rev:
        return f"Nothing done: `{NS}/{DEPLOY}` is now on revision {current}, not {from_rev} (already rolled back or redeployed)."

    selector = dep["spec"]["selector"]["matchLabels"]
    target = next((rs for rs in kube.list_replicasets(NS, selector) if revision_of(rs) == to_rev), None)
    if target is None:
        return f"Nothing done: revision {to_rev} no longer exists for `{NS}/{DEPLOY}`."

    template = target["spec"]["template"]
    template.get("metadata", {}).get("labels", {}).pop("pod-template-hash", None)
    kube.patch_deployment(NS, DEPLOY, [
        # test op: the patch fails atomically if someone deployed in between
        {"op": "test", "path": "/metadata/annotations/deployment.kubernetes.io~1revision", "value": str(from_rev)},
        {"op": "replace", "path": "/spec/template", "value": template},
    ])
    version = template.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/version", "?")
    return f"Rolled back `{NS}/{DEPLOY}` from revision {from_rev} to the template of revision {to_rev} (version {version})."


def lambda_handler(event, context):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    slack = secret("slack")
    if not verify_slack_signature(slack["signing_secret"], headers, raw):
        logger.warning("rejected request with bad/missing Slack signature")
        return _reply(401, "invalid signature")

    payload = json.loads(urllib.parse.parse_qs(raw).get("payload", ["{}"])[0])
    if payload.get("type") != "block_actions" or not payload.get("actions"):
        return _reply(200)  # e.g. Slack URL verification pings, other interactions
    action = payload["actions"][0]
    user = payload.get("user", {})
    who = user.get("username") or user.get("name") or user.get("id", "someone")
    response_url = payload.get("response_url")

    if action.get("action_id") != "approve_rollback":
        return _reply(200)
    try:
        value = json.loads(action.get("value", "{}"))
        from_rev, to_rev = int(value["from_rev"]), int(value["to_rev"])
    except (ValueError, KeyError, TypeError):
        return _reply(400, "bad button value")
    if value.get("ns") != NS or value.get("deploy") != DEPLOY:
        logger.warning("refused rollback for %s/%s", value.get("ns"), value.get("deploy"))
        return _reply(403, "not allowed for this deployment")

    logger.info("rollback approved by %s (%s): rev %s -> %s", who, user.get("id"), from_rev, to_rev)
    try:
        result = rollback(Kube(), from_rev, to_rev)
        ok = result.startswith("Rolled back")
    except Exception as exc:
        logger.exception("rollback failed")
        result, ok = f"Rollback FAILED: {type(exc).__name__}: {str(exc)[:300]}", False

    text = f"{'✅' if ok else '⚠️'} {result} Approved by <@{user.get('id')}>."
    if response_url:
        original = payload.get("message", {}).get("blocks", [])
        kept = [b for b in original if b.get("type") != "actions"]  # remove the button
        kept.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
        try:
            slack_respond(response_url, {"replace_original": True, "text": text, "blocks": kept})
        except Exception:
            logger.exception("Slack update failed")

    if value.get("jira"):
        try:
            jira_comment(secret("jira"), value["jira"], f"{result} Approved in Slack by {who}.")
        except Exception:
            logger.exception("Jira comment failed")

    return _reply(200)
