# Zips the packages built by scripts/build_lambdas.sh (run it before apply;
# cluster.sh does). Sources: lambdas/<name>/handler.py + agent/*.py + deps.

data "archive_file" "analyzer" {
  type        = "zip"
  source_dir  = "${path.module}/.build/src/analyzer"
  output_path = "${path.module}/.build/analyzer.zip"
}

data "archive_file" "executor" {
  type        = "zip"
  source_dir  = "${path.module}/.build/src/executor"
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
  description      = "Read-only incident analyzer: evidence -> mask -> Claude decision -> router -> Slack/Jira"
  role             = aws_iam_role.analyzer.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.analyzer.output_path
  source_code_hash = data.archive_file.analyzer.output_base64sha256
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      CLUSTER_NAME      = local.cluster_name
      APP_NAMESPACE     = var.app_namespace
      APP_DEPLOYMENT    = var.app_name
      APP_LOG_GROUP     = aws_cloudwatch_log_group.application.name
      METRIC_NAMESPACE  = local.metric_namespace
      CONFIG_SECRET_ARN = aws_secretsmanager_secret.config.arn
      MIN_CONFIDENCE    = tostring(var.min_confidence)
      CLAUDE_MODEL      = var.claude_model
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

  # -1 = unreserved. New accounts have a 10-execution account limit and AWS
  # refuses any reservation that drops unreserved below 10. The executor is
  # idempotent instead: it only rolls back if the Deployment is still on the
  # revision named in the Slack button, so a double-click is a no-op.
  reserved_concurrent_executions = var.executor_reserved_concurrency

  environment {
    variables = {
      CLUSTER_NAME      = local.cluster_name
      APP_NAMESPACE     = var.app_namespace
      APP_DEPLOYMENT    = var.app_name
      CONFIG_SECRET_ARN = aws_secretsmanager_secret.config.arn
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

# Since late 2025, a public (auth NONE) Function URL also needs lambda:InvokeFunction
# restricted to URL calls (condition lambda:InvokedViaFunctionUrl), or AWS answers 403
# before the function runs. aws provider 5.x (pinned by the EKS module) has no
# argument for that condition, so the AWS CLI adds it. Re-runs if the function is replaced.
resource "terraform_data" "executor_url_invoke_permission" {
  triggers_replace = [aws_lambda_function.executor.arn]

  provisioner "local-exec" {
    command = <<-CMD
      aws lambda add-permission --region ${var.region} \
        --function-name ${aws_lambda_function.executor.function_name} \
        --statement-id AllowPublicInvokeViaFunctionUrl \
        --action lambda:InvokeFunction --principal '*' --invoked-via-function-url \
        --output text --query Statement >/dev/null 2>&1 \
      || aws lambda get-policy --region ${var.region} \
        --function-name ${aws_lambda_function.executor.function_name} \
        --query Policy --output text | grep -q AllowPublicInvokeViaFunctionUrl
    CMD
  }

  depends_on = [aws_lambda_permission.executor_url_public]
}
