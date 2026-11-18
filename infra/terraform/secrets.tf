# Terraform only creates the secret containers. Put the values in yourself so
# they never land in state (commands are in the README's "Secrets" section):
#
#   slack: {"bot_token": "xoxb-...", "signing_secret": "...", "channel_id": "C..."}
#   jira:  {"base_url": "https://<site>.atlassian.net", "email": "...", "api_token": "...", "project_key": "OPS"}
# (Jev is on hold; add "jev" back here when it returns.)
locals {
  secret_names = ["slack", "jira"]
}

resource "aws_secretsmanager_secret" "this" {
  for_each = toset(local.secret_names)

  name                    = "${var.name}/${each.key}"
  recovery_window_in_days = 0 # demo: allow destroy + re-create with the same name
}
