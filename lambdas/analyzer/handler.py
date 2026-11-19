"""Analyzer Lambda: READ-ONLY. Triggered by EventBridge when the demo-shop alarm enters ALARM.

  1. Evidence in code: Logs Insights (error sample + counts per version), GetMetricData,
     Deployment rollout history (ReplicaSets) from the EKS API.
  2. Mask PII before anything leaves the function.
  3. agent.incident.decide(): one Claude Haiku call (Claude API) -> typed decision (or None -> human).
  4. agent.router.route_incident(): rollback button only if the model AND code agree.
  5. Jira ticket + Slack message (with [Approve rollback] when offered).

Every step degrades instead of failing: no cluster -> no rollout history; Claude API
unreachable -> "hold for human". The alarm always produces a Slack message and a ticket.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import anthropic
import boto3

from agent.incident import decide
from agent.integrations import (
    Kube, jira_browse_url, jira_create_issue, revision_of, secret, slack_api,
)
from agent.masking import mask
from agent.router import route_incident

logger = logging.getLogger()
logger.setLevel(logging.INFO)

NS = os.environ.get("APP_NAMESPACE", "demo")
DEPLOY = os.environ.get("APP_DEPLOYMENT", "demo-shop")
LOG_GROUP = os.environ.get("APP_LOG_GROUP", "")
METRIC_NS = os.environ.get("METRIC_NAMESPACE", "")
MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "0.85"))

LOOKBACK = timedelta(minutes=30)          # evidence window before the alarm
RECENT_ROLLOUT = timedelta(minutes=20)    # "new revision right before the alarm"


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def _logs_query(query: str, start: datetime, end: datetime) -> list[dict]:
    logs = boto3.client("logs")
    qid = logs.start_query(
        logGroupName=LOG_GROUP, queryString=query,
        startTime=int(start.timestamp()), endTime=int(end.timestamp()) + 60,
    )["queryId"]
    for _ in range(40):
        res = logs.get_query_results(queryId=qid)
        if res["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            return [{f["field"]: f["value"] for f in row} for row in res.get("results", [])]
        time.sleep(1)
    logs.stop_query(queryId=qid)
    return []


def _log_line(message: str) -> str:
    """Fluent Bit wraps the container line as JSON {"log": "...", "kubernetes": {...}}."""
    try:
        return json.loads(message).get("log", message).strip()
    except (ValueError, AttributeError):
        return message.strip()


def collect_logs(start: datetime, end: datetime) -> tuple[list[str], list[str]]:
    sample = _logs_query(
        "fields @timestamp, @message | filter @message like /ERROR|status=5/ "
        "| sort @timestamp desc | limit 15", start, end)
    counts = _logs_query(
        "fields @message | parse @message /(?<level>INFO|ERROR) \\[(?<ver>[^\\]]+)\\]/ "
        "| filter ispresent(level) | stats count() as n, min(@timestamp) as first, "
        "max(@timestamp) as last by ver, level", start, end)
    sample_lines = [mask(_log_line(r.get("@message", ""))) for r in sample]
    count_lines = [
        f"version={r.get('ver')} level={r.get('level')} lines={r.get('n')} "
        f"first={r.get('first')} last={r.get('last')}" for r in counts
    ]
    return sample_lines, count_lines


def collect_metrics(start: datetime, end: datetime) -> list[str]:
    cw = boto3.client("cloudwatch")
    queries = [
        {"Id": name.lower(), "Label": name, "ReturnData": True, "MetricStat": {
            "Metric": {"Namespace": METRIC_NS, "MetricName": name}, "Period": 60, "Stat": "Sum"}}
        for name in ("DbConnectionErrors", "Http5xx")
    ]
    res = cw.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end + timedelta(minutes=1),
                             ScanBy="TimestampAscending")
    out = []
    for r in res["MetricDataResults"]:
        points = ", ".join(f"{t:%H:%M}={int(v)}" for t, v in zip(r["Timestamps"], r["Values"]))
        out.append(f"{r['Label']} per minute: {points or 'no data'}")
    return out


def collect_rollouts(alarm_time: datetime) -> tuple[list[str], dict]:
    """Returns (history lines, facts). facts: current/previous revision, recent flag."""
    facts = {"current_rev": None, "previous_rev": None, "new_revision_in_window": False}
    try:
        kube = Kube()
        dep = kube.get_deployment(NS, DEPLOY)
        selector = dep["spec"]["selector"]["matchLabels"]
        rsets = sorted(kube.list_replicasets(NS, selector), key=revision_of, reverse=True)
    except Exception as exc:  # cluster down, auth, RBAC: evidence without history
        logger.warning("rollout history unavailable: %s", exc)
        return [f"Rollout history unavailable ({type(exc).__name__})."], facts

    current = revision_of(dep)
    lines = []
    for rs in rsets:
        rev = revision_of(rs)
        created = rs["metadata"]["creationTimestamp"]
        version = rs["spec"]["template"]["metadata"].get("labels", {}).get("app.kubernetes.io/version", "?")
        env = {e["name"]: e.get("value") for c in rs["spec"]["template"]["spec"]["containers"] for e in c.get("env", [])}
        changes = ", ".join(f"{k}={v}" for k, v in sorted(env.items()))
        marker = " (CURRENT)" if rev == current else ""
        lines.append(f"revision {rev}{marker}: version={version}, created {created}, "
                     f"ready={rs.get('status', {}).get('readyReplicas', 0)}, env: {changes}")

    facts["current_rev"] = current
    older = [revision_of(rs) for rs in rsets if revision_of(rs) < current]
    facts["previous_rev"] = max(older) if older else None
    cur_rs = next((rs for rs in rsets if revision_of(rs) == current), None)
    if cur_rs and facts["previous_rev"]:
        created = datetime.fromisoformat(cur_rs["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
        facts["new_revision_in_window"] = alarm_time - RECENT_ROLLOUT <= created <= alarm_time + timedelta(minutes=1)
    return lines, facts


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def slack_blocks(alarm: str, decision, route, facts: dict, jira_key: str | None, jira_url: str | None) -> list[dict]:
    if decision:
        head = (f"*{decision.root_cause}* · severity {decision.severity}/10 · "
                f"confidence {decision.confidence:.2f}\n{decision.summary}")
        evidence = "\n".join(f"• {e}" for e in decision.evidence[:5])
    else:
        head = "The model gave no usable decision (unavailable or declined). A human needs to look."
        evidence = ""
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🚨 {DEPLOY} incident: {alarm}"[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": head[:2900]}},
    ]
    if evidence:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Evidence*\n{evidence}"[:2900]}})
    ctx = f"Routing: *{route.action}* ({route.reason})"
    if jira_key:
        ctx += f" · Jira <{jira_url}|{jira_key}>"
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ctx}]})
    if route.action == "offer_rollback":
        value = json.dumps({"ns": NS, "deploy": DEPLOY, "from_rev": facts["current_rev"],
                            "to_rev": facts["previous_rev"], "jira": jira_key})
        blocks.append({"type": "actions", "elements": [{
            "type": "button", "style": "danger", "action_id": "approve_rollback", "value": value,
            "text": {"type": "plain_text", "text": f"Approve rollback to revision {facts['previous_rev']}"},
            "confirm": {
                "title": {"type": "plain_text", "text": "Roll back?"},
                "text": {"type": "mrkdwn", "text": f"Roll `{NS}/{DEPLOY}` back from revision "
                                                   f"{facts['current_rev']} to {facts['previous_rev']}."},
                "confirm": {"type": "plain_text", "text": "Roll back"},
                "deny": {"type": "plain_text", "text": "Cancel"},
            },
        }]})
    return blocks


def lambda_handler(event, context):
    detail = event.get("detail", {})
    alarm = detail.get("alarmName", "unknown-alarm")
    state = detail.get("state", {})
    if state.get("value") != "ALARM":
        return {"status": "ignored", "state": state.get("value")}
    ts = state.get("timestamp")
    alarm_time = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else datetime.now(timezone.utc)
    alarm_time = alarm_time.replace(tzinfo=alarm_time.tzinfo or timezone.utc)
    start = alarm_time - LOOKBACK

    sample, counts = collect_logs(start, alarm_time)
    metrics = collect_metrics(start, alarm_time)
    history, facts = collect_rollouts(alarm_time)

    evidence_text = "\n".join([
        f"Alarm {alarm} entered ALARM at {alarm_time:%Y-%m-%d %H:%M:%S} UTC "
        f"({mask(state.get('reason', ''))}).",
        f"Service: Deployment {NS}/{DEPLOY} on EKS.",
        "", "Rollout history (newest first):", *history,
        "", "Log line counts per version and level in the last 30 minutes:", *(counts or ["none"]),
        "", "Metrics:", *metrics,
        "", "Most recent error lines (PII masked):", *(sample or ["none"]),
    ])
    logger.info("evidence:\n%s", evidence_text)

    try:
        client = anthropic.Anthropic(api_key=secret("anthropic")["api_key"], max_retries=2)
        decision = decide(evidence_text, model=os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5"), client=client)
    except Exception:  # 429/5xx after retries, network: a human decides instead
        logger.exception("Claude call failed")
        decision = None
    route = route_incident(
        decision.root_cause if decision else None,
        decision.rollback_likely_fixes if decision else False,
        decision.confidence if decision else 0.0,
        new_revision_in_window=facts["new_revision_in_window"],
        min_confidence=MIN_CONFIDENCE,
    )
    logger.info("decision=%s route=%s facts=%s", decision, route, facts)

    jira_key = jira_url = None
    try:
        jira = secret("jira")
        summary = (f"[{DEPLOY}] {decision.root_cause}: {alarm}" if decision else f"[{DEPLOY}] needs triage: {alarm}")
        body = "\n".join([
            decision.summary if decision else "The model gave no usable decision. A human needs to look.",
            "", f"Routing: {route.action} ({route.reason})", "", "Evidence collected by code:", evidence_text,
        ])
        jira_key = jira_create_issue(jira, summary, body, labels=["incident-agent", DEPLOY])
        jira_url = jira_browse_url(jira, jira_key)
    except Exception:
        logger.exception("Jira ticket failed; continuing with Slack")

    slack = secret("slack")
    slack_api("chat.postMessage", {
        "channel": slack["channel_id"],
        "text": f"{DEPLOY} incident: {alarm} ({route.action})",
        "blocks": slack_blocks(alarm, decision, route, facts, jira_key, jira_url),
        "unfurl_links": False,
    }, slack["bot_token"])

    return {"status": "posted", "route": route.action, "jira": jira_key}
