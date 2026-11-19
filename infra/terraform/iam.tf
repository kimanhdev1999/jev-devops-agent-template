data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  # Known even while the cluster is down, so Lambdas/IAM don't change on toggle.
  cluster_name = var.name
  cluster_arn  = "arn:${local.partition}:eks:${var.region}:${local.account_id}:cluster/${var.name}"
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---------------------------------------------------------------------------
# Analyzer: READ-ONLY. Logs, metrics, cluster read (via access entry), secrets,
# and the config secret (Claude API key). It cannot change anything in the cluster.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "analyzer" {
  name               = "${var.name}-analyzer"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "analyzer_basic" {
  role       = aws_iam_role.analyzer.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "analyzer" {
  statement {
    sid       = "LogsInsightsOnAppLogs"
    actions   = ["logs:StartQuery", "logs:FilterLogEvents"]
    resources = [aws_cloudwatch_log_group.application.arn, "${aws_cloudwatch_log_group.application.arn}:*"]
  }

  statement {
    sid = "MetricsRead"
    # These actions don't support resource-level permissions.
    actions   = ["cloudwatch:GetMetricData", "cloudwatch:DescribeAlarms", "logs:GetQueryResults", "logs:StopQuery"]
    resources = ["*"]
  }

  statement {
    sid       = "ClusterEndpoint"
    actions   = ["eks:DescribeCluster"]
    resources = [local.cluster_arn]
  }

  statement {
    sid       = "ReadIntegrationSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.config.arn]
  }

}

resource "aws_iam_role_policy" "analyzer" {
  name   = "analyzer-read-only"
  role   = aws_iam_role.analyzer.id
  policy = data.aws_iam_policy_document.analyzer.json
}

# ---------------------------------------------------------------------------
# Executor: the only identity that can change the cluster, and only through the
# Kubernetes Role in k8s.tf. AWS-side it just needs the cluster endpoint, the
# Slack secret (signature check + updating the message) and the Jira secret
# (commenting "rolled back by <user>" on the ticket).
# ---------------------------------------------------------------------------
resource "aws_iam_role" "executor" {
  name               = "${var.name}-executor"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "executor_basic" {
  role       = aws_iam_role.executor.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "executor" {
  statement {
    sid       = "ClusterEndpoint"
    actions   = ["eks:DescribeCluster"]
    resources = [local.cluster_arn]
  }

  statement {
    sid       = "ReadSlackAndJiraSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.config.arn]
  }
}

resource "aws_iam_role_policy" "executor" {
  name   = "executor-rollback"
  role   = aws_iam_role.executor.id
  policy = data.aws_iam_policy_document.executor.json
}
