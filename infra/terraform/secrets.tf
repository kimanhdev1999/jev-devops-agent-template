# ONE secret for every integration ($0.40/month per secret, so one instead of three).
# Terraform only creates the container. Fill it with scripts/put_config_secret.sh,
# so the values never land in Terraform state:
#
#   {
#     "slack":     {"bot_token": "xoxb-...", "signing_secret": "...", "channel_id": "C..."},
#     "jira":      {"base_url": "https://<site>.atlassian.net", "email": "...", "api_token": "...",
#                   "project_key": "KAN", "issue_type": "Bug"},
#     "anthropic": {"api_key": "sk-ant-..."}
#   }
resource "aws_secretsmanager_secret" "config" {
  name                    = "${var.name}/config"
  description             = "Slack, Jira and Claude API credentials for the incident agent"
  recovery_window_in_days = 0 # demo: allow destroy + re-create with the same name
}
