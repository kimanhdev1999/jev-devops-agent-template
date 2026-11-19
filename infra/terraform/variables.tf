variable "name" {
  description = "Prefix for every resource (cluster, Lambdas, secrets, alarm)."
  type        = string
  default     = "jev-incident-demo"
}

variable "region" {
  description = "AWS Region. Mumbai was picked for price and Haiku access."
  type        = string
  default     = "ap-south-1"
}

variable "enable_cluster" {
  description = "false = destroy only EKS, its nodes and the in-cluster resources (saves ~$0.20/h). Lambdas, secrets, the Slack Function URL, alarm and log group stay. Use ./cluster.sh up|down instead of setting this by hand."
  type        = bool
  default     = true
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version. Use one in STANDARD support: extended support raises the control plane from $0.10 to $0.60/hour."
  type        = string
  default     = "1.37"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "node_instance_type" {
  description = "Worker node type. t3.small (2 GiB, 11 pods/node) is the cheapest that fits: t3.micro allows only 4 pods/node, fewer than the per-node DaemonSets. Use t3.medium (4 GiB, 17 pods/node) for more headroom."
  type        = string
  default     = "t3.small"
}

variable "node_count" {
  type    = number
  default = 2
}

variable "app_namespace" {
  description = "Namespace for the demo app. The executor's write access is limited to it."
  type        = string
  default     = "demo"
}

variable "app_name" {
  description = "Helm release / Deployment name of the demo app. The only Deployment the executor may roll back."
  type        = string
  default     = "demo-shop"
}

variable "alarm_error_threshold" {
  description = "DB connection errors per minute that put the alarm into ALARM."
  type        = number
  default     = 5
}

variable "claude_model" {
  description = "Claude model on the Claude API (key in the config secret). Makes the incident decision and writes the Slack/Jira text."
  type        = string
  default     = "claude-haiku-5-5"
}

variable "min_confidence" {
  description = "Minimum (self-reported, uncalibrated) model confidence on root_cause=bad_deploy before Slack offers a rollback button. A recent rollout seen in code is also required."
  type        = number
  default     = 0.85
}

variable "admin_principal_arns" {
  description = "Extra IAM principals (e.g. your SSO role) to give cluster-admin through EKS access entries. The identity running terraform is added automatically."
  type        = list(string)
  default     = []
}

variable "executor_reserved_concurrency" {
  description = "Reserved concurrency for the executor. -1 = none (needed on accounts with the default 10-execution limit). Set 1 once the account limit is raised."
  type        = number
  default     = -1
}
