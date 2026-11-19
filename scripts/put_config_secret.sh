#!/usr/bin/env bash
# Build the ONE config secret (jev-incident-demo/config) from local files, without
# printing or committing any value. Checks every credential before storing it.
#
#   ~/.slack_jev_demo            bot_token=xoxb-...  signing_secret=...  channel=incidents
#   ~/.atlassian_token_sre_will  the Jira API token (one line)
#   ~/.claude-api-token-will     the Claude API key, sk-ant-... (one line)
#   ~/.jira_jev_demo             base_url=https://<site>.atlassian.net  email=...  project=KAN  issue_type=Bug
#
# JIRA_* env vars override the values in ~/.jira_jev_demo.
set -euo pipefail
: "${AWS_PROFILE:=will}"; : "${AWS_REGION:=ap-south-1}"; export AWS_PROFILE AWS_REGION
export SLACK_FILE="${SLACK_FILE:-$HOME/.slack_jev_demo}"
export JIRA_TOKEN_FILE="${JIRA_TOKEN_FILE:-$HOME/.atlassian_token_sre_will}"
export CLAUDE_KEY_FILE="${CLAUDE_KEY_FILE:-$HOME/.claude-api-token-will}"
JIRA_FILE="${JIRA_FILE:-$HOME/.jira_jev_demo}"
jira_get() { [ -f "$JIRA_FILE" ] && sed -n "s/^$1=//p" "$JIRA_FILE" | head -1; }
export JIRA_BASE_URL="${JIRA_BASE_URL:-$(jira_get base_url)}"
export JIRA_EMAIL="${JIRA_EMAIL:-$(jira_get email)}"
export JIRA_PROJECT="${JIRA_PROJECT:-$(jira_get project)}"
export JIRA_ISSUE_TYPE="${JIRA_ISSUE_TYPE:-$(jira_get issue_type)}"
: "${JIRA_BASE_URL:?set base_url in $JIRA_FILE}" "${JIRA_EMAIL:?set email in $JIRA_FILE}"
export JIRA_PROJECT="${JIRA_PROJECT:-KAN}" JIRA_ISSUE_TYPE="${JIRA_ISSUE_TYPE:-Bug}"
export SECRET_ID="${SECRET_ID:-jev-incident-demo/config}"
chmod 600 "$SLACK_FILE" "$JIRA_TOKEN_FILE" "$CLAUDE_KEY_FILE"

python3 - <<'PY'
import base64, json, os, subprocess, sys, tempfile, urllib.error, urllib.parse, urllib.request
E = os.environ
read = lambda p: open(p).read().strip()

def call(url, headers=None, data=None):
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    try:
        return json.load(urllib.request.urlopen(req, timeout=15))
    except urllib.error.HTTPError as e:
        sys.exit(f"{url.split('?')[0]} -> HTTP {e.code}")

# Slack
s = dict(l.strip().split("=", 1) for l in open(E["SLACK_FILE"]) if "=" in l and not l.startswith("#"))
tok, chan = s["bot_token"], s["channel"].lstrip("#")
slack = lambda m, **p: call(f"https://slack.com/api/{m}?{urllib.parse.urlencode(p)}", {"Authorization": f"Bearer {tok}"})
a = slack("auth.test")
if not a.get("ok"): sys.exit(f"Slack token rejected: {a.get('error')}")
if not (chan.startswith("C") and chan.isupper()):
    cid, cursor = None, ""
    while True:
        r = slack("conversations.list", types="public_channel", limit=1000, exclude_archived="true", cursor=cursor)
        if not r.get("ok"): sys.exit(f"conversations.list: {r.get('error')}")
        cid = next((c["id"] for c in r["channels"] if c["name"] == chan), None)
        cursor = r.get("response_metadata", {}).get("next_cursor")
        if cid or not cursor: break
    if not cid: sys.exit(f"public channel #{chan} not found")
    chan = cid
print(f"slack     OK  bot={a['user']} workspace={a['team']} channel={chan}")

# Jira
jt = read(E["JIRA_TOKEN_FILE"])
auth = base64.b64encode(f"{E['JIRA_EMAIL']}:{jt}".encode()).decode()
me = call(E["JIRA_BASE_URL"] + "/rest/api/3/myself", {"Authorization": f"Basic {auth}", "Accept": "application/json"})
print(f"jira      OK  {me.get('displayName')} -> {E['JIRA_PROJECT']} ({E['JIRA_ISSUE_TYPE']})")

# Claude
key = read(E["CLAUDE_KEY_FILE"])
call("https://api.anthropic.com/v1/models?limit=1", {"x-api-key": key, "anthropic-version": "2023-06-01"})
print("anthropic OK  key accepted")

cfg = {
    "slack": {"bot_token": tok, "signing_secret": s["signing_secret"], "channel_id": chan},
    "jira": {"base_url": E["JIRA_BASE_URL"], "email": E["JIRA_EMAIL"], "api_token": jt,
             "project_key": E["JIRA_PROJECT"], "issue_type": E["JIRA_ISSUE_TYPE"]},
    "anthropic": {"api_key": key},
}
fd, path = tempfile.mkstemp()
try:
    with os.fdopen(fd, "w") as f: json.dump(cfg, f)
    subprocess.run(["aws", "secretsmanager", "put-secret-value", "--secret-id", E["SECRET_ID"],
                    "--secret-string", f"file://{path}", "--query", "Name", "--output", "text"], check=True)
finally:
    os.remove(path)
print(f"stored {E['SECRET_ID']}")
PY
