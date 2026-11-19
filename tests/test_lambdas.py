import hashlib
import hmac
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.masking import mask
from agent.router import IncidentRoute

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_handler", ROOT / "lambdas" / name / "handler.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


analyzer = _load("analyzer")
executor = _load("executor")


# --- masking -------------------------------------------------------------

def test_mask_removes_pii_and_secrets():
    line = ("ERROR [v2] db connection refused host=orders-db:5432 order=482913 "
            "customer=alice@example.com ip=10.42.1.7 token=abc123 xoxb-1234-abcd")
    out = mask(line)
    for leaked in ("alice@example.com", "482913", "10.42.1.7", "abc123", "xoxb-1234"):
        assert leaked not in out
    assert "db connection refused host=orders-db:5432" in out  # the useful part survives


# --- Slack signature -----------------------------------------------------

def _signed(secret, body, ts):
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return {"x-slack-request-timestamp": str(ts), "x-slack-signature": sig}


def test_signature_ok():
    assert executor.verify_slack_signature("s3cret", _signed("s3cret", "payload=x", 1000), "payload=x", now=1010)


@pytest.mark.parametrize("secret,body,now", [
    ("wrong", "payload=x", 1010),        # wrong secret
    ("s3cret", "payload=y", 1010),       # body tampered
    ("s3cret", "payload=x", 1000 + 301),  # replay older than 5 min
])
def test_signature_rejected(secret, body, now):
    headers = _signed(secret, "payload=x", 1000)
    assert not executor.verify_slack_signature("s3cret", headers, body, now=now)


def test_signature_missing_headers():
    assert not executor.verify_slack_signature("s3cret", {}, "payload=x", now=1000)


# --- rollback ------------------------------------------------------------

class FakeKube:
    def __init__(self, current_rev):
        self.current_rev = current_rev
        self.patches = []

    def get_deployment(self, ns, name):
        return {"metadata": {"annotations": {"deployment.kubernetes.io/revision": str(self.current_rev)}},
                "spec": {"selector": {"matchLabels": {"app": "demo-shop"}}}}

    def list_replicasets(self, ns, selector):
        def rs(rev, version):
            return {"metadata": {"annotations": {"deployment.kubernetes.io/revision": str(rev)}},
                    "spec": {"template": {"metadata": {"labels": {
                        "app.kubernetes.io/version": version, "pod-template-hash": "abc"}}}}}
        return [rs(1, "v1"), rs(2, "v2")]

    def patch_deployment(self, ns, name, ops):
        self.patches.append(ops)


def test_rollback_patches_previous_template_without_hash():
    kube = FakeKube(current_rev=2)
    result = executor.rollback(kube, from_rev=2, to_rev=1)
    assert result.startswith("Rolled back") and "v1" in result
    test_op, replace_op = kube.patches[0]
    assert test_op == {"op": "test", "path": "/metadata/annotations/deployment.kubernetes.io~1revision", "value": "2"}
    assert replace_op["op"] == "replace" and replace_op["path"] == "/spec/template"
    assert "pod-template-hash" not in replace_op["value"]["metadata"]["labels"]


def test_rollback_is_noop_when_revision_moved():
    kube = FakeKube(current_rev=3)  # already rolled back (undo bumps the revision)
    assert executor.rollback(kube, from_rev=2, to_rev=1).startswith("Nothing done")
    assert kube.patches == []


def test_handler_rejects_unsigned(monkeypatch):
    monkeypatch.setattr(executor, "secret", lambda _: {"signing_secret": "s3cret"})
    resp = executor.lambda_handler({"body": "payload=%7B%7D", "headers": {}}, None)
    assert resp["statusCode"] == 401


def test_handler_refuses_other_deployment(monkeypatch):
    monkeypatch.setattr(executor, "secret", lambda _: {"signing_secret": "s3cret"})
    payload = {"type": "block_actions", "user": {"id": "U1"}, "actions": [{
        "action_id": "approve_rollback",
        "value": json.dumps({"ns": "kube-system", "deploy": "coredns", "from_rev": 2, "to_rev": 1})}]}
    from urllib.parse import urlencode
    body = urlencode({"payload": json.dumps(payload)})
    import time
    resp = executor.lambda_handler({"body": body, "headers": _signed("s3cret", body, int(time.time()))}, None)
    assert resp["statusCode"] == 403


# --- analyzer Slack message ----------------------------------------------

def test_button_only_when_offered():
    decision = SimpleNamespace(root_cause="bad_deploy", severity=8, confidence=0.93,
                               summary="v2 broke DB access.", evidence=["errors began after rev 2"])
    facts = {"current_rev": 2, "previous_rev": 1}
    offered = analyzer.slack_blocks("alarm", decision, IncidentRoute("offer_rollback", "ok"), facts, "KAN-1", "u")
    held = analyzer.slack_blocks("alarm", decision, IncidentRoute("hold_for_human", "x"), facts, "KAN-1", "u")
    assert offered[-1]["type"] == "actions"
    value = json.loads(offered[-1]["elements"][0]["value"])
    assert value == {"ns": "demo", "deploy": "demo-shop", "from_rev": 2, "to_rev": 1, "jira": "KAN-1"}
    assert all(b["type"] != "actions" for b in held)


def test_no_decision_message_still_renders():
    blocks = analyzer.slack_blocks("alarm", None, IncidentRoute("hold_for_human", "none"), {}, None, None)
    assert "human" in blocks[1]["text"]["text"]


def test_log_line_unwraps_fluent_bit_json():
    assert analyzer._log_line('{"log": "ERROR [v2] boom\\n", "kubernetes": {}}') == "ERROR [v2] boom"
    assert analyzer._log_line("plain text") == "plain text"
