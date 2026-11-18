# Packages the source directories as-is. Third-party dependencies (httpx,
# anthropic[bedrock], kubernetes client, etc.) must be vendored into the directory before apply,
# e.g. `pip install -r requirements.txt -t lambdas/analyzer/` (see README).
data "archive_file" "analyzer" {
  type        = "zip"
  source_dir  = "${path.module}/../../lambdas/analyzer"
  output_path = "${path.module}/.build/analyzer.zip"
}

data "archive_file" "executor" {
  type        = "zip"
  source_dir  = "${path.module}/../../lambdas/executor"
  output_path = "${path.module}/.build/executor.zip"
}

resource "aws_cloudwatch_log_group" "analyzer" {
  name              = "/aws/lambda/${var.name}-analyzer"
  retention_in_days = 3
}

resource "aws_cloudwatch_log_group" "executor" {
  name              = "/aws/lambda/${var.name}-executor"
  retention_in_days = 3
}

resource "aws_lambda_function" "analyzer" {
  function_name    = "${var.name}-analyzer"
  description      = "Read-only incident analyzer: evidence -> mask -> Haiku decision -> router -> Slack/Jira"
  role             = aws_iam_role.analyzer.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.analyzer.output_path
  source_code_hash = data.archive_file.analyzer.output_base64sha256
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      CLUSTER_NAME     = local.cluster_name
      APP_NAMESPACE    = var.app_namespace
      APP_DEPLOYMENT   = var.app_name
      APP_LOG_GROUP    = aws_cloudwatch_log_group.application.name
      METRIC_NAMESPACE = local.metric_namespace
      SLACK_SECRET_ARN = aws_secretsmanager_secret.this["slack"].arn
      JIRA_SECRET_ARN  = aws_secretsmanager_secret.this["jira"].arn
      MIN_CONFIDENCE   = tostring(var.min_confidence)
      BEDROCK_MODEL_ID = var.bedrock_model_id
    }
  }

  depends_on = [aws_cloudwatch_log_group.analyzer, aws_iam_role_policy_attachment.analyzer_basic]
}

resource "aws_lambda_function" "executor" {
  function_name    = "${var.name}-executor"
  description      = "Runs ONLY after a human clicks Approve in Slack: rolls back one Deployment"
  role             = aws_iam_role.executor.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.executor.output_path
  source_code_hash = data.archive_file.executor.output_base64sha256
  timeout          = 30
  memory_size      = 256

  # One rollback at a time; double-clicks queue/throttle instead of racing.
  reserved_concurrent_executions = 1

  environment {
    variables = {
      CLUSTER_NAME     = local.cluster_name
      APP_NAMESPACE    = var.app_namespace
      APP_DEPLOYMENT   = var.app_name
      SLACK_SECRET_ARN = aws_secretsmanager_secret.this["slack"].arn
      JIRA_SECRET_ARN  = aws_secretsmanager_secret.this["jira"].arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.executor, aws_iam_role_policy_attachment.executor_basic]
}

# Slack interactivity can't sign requests with SigV4, so the URL is public
# (auth NONE). The executor MUST verify the X-Slack-Signature header with the
# signing secret and reject anything older than 5 minutes before acting.
resource "aws_lambda_function_url" "executor" {
  function_name      = aws_lambda_function.executor.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "executor_url_public" {
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.executor.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}
