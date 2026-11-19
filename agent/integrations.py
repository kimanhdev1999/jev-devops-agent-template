"""Thin clients for the Lambdas: Secrets Manager, EKS/Kubernetes, Slack, Jira.

Standard library + boto3 only (boto3 ships with the Lambda runtime), so the
executor package stays tiny and cold-starts well inside Slack's 3 s limit.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

import boto3
from botocore.signers import RequestSigner

HTTP_TIMEOUT = 10


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} from {url}: {body[:300]}")
        self.status = status
        self.body = body


def _http(method: str, url: str, *, headers: dict | None = None, body: bytes | None = None,
          context: ssl.SSLContext | None = None) -> dict | list | None:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=context) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(exc.code, exc.read().decode(errors="replace"), url) from None
    return json.loads(raw) if raw else None


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _config() -> dict:
    value = boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["CONFIG_SECRET_ARN"])
    return json.loads(value["SecretString"])


def secret(section: str) -> dict:
    """One section ("slack", "jira", "anthropic") of the single config secret."""
    return _config()[section]


# ---------------------------------------------------------------------------
# EKS / Kubernetes
# ---------------------------------------------------------------------------

def eks_token(cluster: str, region: str) -> str:
    """Bearer token for the EKS API: a presigned STS GetCallerIdentity URL
    (what `aws eks get-token` produces). Valid ~15 min."""
    session = boto3.session.Session()
    sts = session.client("sts", region_name=region)
    signer = RequestSigner(
        sts.meta.service_model.service_id, region, "sts", "v4",
        session.get_credentials(), session.events,
    )
    url = signer.generate_presigned_url(
        {
            "method": "GET",
            "url": f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15",
            "body": {},
            "headers": {"x-k8s-aws-id": cluster},
            "context": {},
        },
        region_name=region,
        expires_in=60,
        operation_name="",
    )
    return "k8s-aws-v1." + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


class Kube:
    """Minimal Kubernetes REST client authenticated with the Lambda's IAM role."""

    def __init__(self, cluster: str | None = None, region: str | None = None):
        self.cluster = cluster or os.environ["CLUSTER_NAME"]
        self.region = region or os.environ.get("AWS_REGION", "ap-south-1")
        info = boto3.client("eks", region_name=self.region).describe_cluster(name=self.cluster)["cluster"]
        self.endpoint = info["endpoint"]
        ca_pem = base64.b64decode(info["certificateAuthority"]["data"]).decode()
        self.ssl = ssl.create_default_context(cadata=ca_pem)
        self.token = eks_token(self.cluster, self.region)

    def request(self, method: str, path: str, *, body: object | None = None,
                content_type: str = "application/json") -> dict:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = content_type
            data = json.dumps(body).encode()
        return _http(method, self.endpoint + path, headers=headers, body=data, context=self.ssl)

    def get_deployment(self, ns: str, name: str) -> dict:
        return self.request("GET", f"/apis/apps/v1/namespaces/{ns}/deployments/{name}")

    def list_replicasets(self, ns: str, selector: dict[str, str]) -> list[dict]:
        sel = urllib.parse.quote(",".join(f"{k}={v}" for k, v in selector.items()))
        return self.request("GET", f"/apis/apps/v1/namespaces/{ns}/replicasets?labelSelector={sel}")["items"]

    def patch_deployment(self, ns: str, name: str, ops: list[dict]) -> dict:
        return self.request("PATCH", f"/apis/apps/v1/namespaces/{ns}/deployments/{name}",
                            body=ops, content_type="application/json-patch+json")


REVISION_ANNOTATION = "deployment.kubernetes.io/revision"


def revision_of(obj: dict) -> int:
    return int(obj.get("metadata", {}).get("annotations", {}).get(REVISION_ANNOTATION, "0"))


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def slack_api(method: str, payload: dict, token: str) -> dict:
    resp = _http(
        "POST", f"https://slack.com/api/{method}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        body=json.dumps(payload).encode(),
    )
    if not resp.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {resp.get('error')}")
    return resp


def slack_respond(response_url: str, payload: dict) -> None:
    """Update the message the button was clicked on (no token needed)."""
    _http("POST", response_url, headers={"Content-Type": "application/json"},
          body=json.dumps(payload).encode())


# ---------------------------------------------------------------------------
# Jira Cloud (REST v3, basic auth with an API token)
# ---------------------------------------------------------------------------

def _adf(text: str) -> dict:
    """Plain text -> Atlassian Document Format (one paragraph per line)."""
    paragraphs = [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]} if line else {"type": "paragraph"}
        for line in text.splitlines()
    ]
    return {"type": "doc", "version": 1, "content": paragraphs or [{"type": "paragraph"}]}


def _jira_headers(cfg: dict) -> dict:
    auth = base64.b64encode(f"{cfg['email']}:{cfg['api_token']}".encode()).decode()
    return {"Authorization": f"Basic {auth}", "Content-Type": "application/json", "Accept": "application/json"}


def jira_create_issue(cfg: dict, summary: str, description: str, labels: list[str]) -> str:
    body = {
        "fields": {
            "project": {"key": cfg["project_key"]},
            "issuetype": {"name": cfg.get("issue_type", "Bug")},
            "summary": summary[:250],
            "description": _adf(description),
            "labels": labels,
        }
    }
    resp = _http("POST", cfg["base_url"].rstrip("/") + "/rest/api/3/issue",
                 headers=_jira_headers(cfg), body=json.dumps(body).encode())
    return resp["key"]


def jira_comment(cfg: dict, key: str, text: str) -> None:
    _http("POST", cfg["base_url"].rstrip("/") + f"/rest/api/3/issue/{key}/comment",
          headers=_jira_headers(cfg), body=json.dumps({"body": _adf(text)}).encode())


def jira_browse_url(cfg: dict, key: str) -> str:
    return cfg["base_url"].rstrip("/") + f"/browse/{key}"
