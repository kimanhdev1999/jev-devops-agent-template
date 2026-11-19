locals {
  app_log_group    = "/aws/containerinsights/${var.name}/application"
  metric_namespace = "${var.name}/demo-shop"
}

# Created here (instead of letting Fluent Bit auto-create it) so the metric
# filters can attach on the first apply and retention stays short.
resource "aws_cloudwatch_log_group" "application" {
  name              = local.app_log_group
  retention_in_days = 1
}

# The incident signal: the broken v2 logs "ERROR db connection refused".
resource "aws_cloudwatch_log_metric_filter" "db_errors" {
  name           = "${var.name}-db-connection-errors"
  log_group_name = aws_cloudwatch_log_group.application.name
  pattern        = "\"ERROR\" \"db connection refused\""

  metric_transformation {
    name      = "DbConnectionErrors"
    namespace = local.metric_namespace
    value     = "1"
    # 0 for every non-matching (healthy) line, so the alarm sees real zeros and
    # returns to OK after a fix; with no datapoints at all it stays in ALARM.
    default_value = 0
  }
}

# Secondary evidence the analyzer pulls with GetMetricData (not alarmed on).
resource "aws_cloudwatch_log_metric_filter" "http_5xx" {
  name           = "${var.name}-http-5xx"
  log_group_name = aws_cloudwatch_log_group.application.name
  pattern        = "\"status=500\""

  metric_transformation {
    name      = "Http5xx"
    namespace = local.metric_namespace
    value     = "1"
    # 0 for every non-matching (healthy) line, so the alarm sees real zeros and
    # returns to OK after a fix; with no datapoints at all it stays in ALARM.
    default_value = 0
  }
}

resource "aws_cloudwatch_metric_alarm" "db_errors" {
  alarm_name          = "${var.name}-demo-shop-db-errors"
  alarm_description   = "demo-shop is logging DB connection errors. Triggers the Jev incident analyzer."
  namespace           = local.metric_namespace
  metric_name         = aws_cloudwatch_log_metric_filter.db_errors.metric_transformation[0].name
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = var.alarm_error_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
}

# Alarm -> analyzer. EventBridge receives alarm state changes on the default
# bus without any alarm action, so no SNS topic is needed.
resource "aws_cloudwatch_event_rule" "alarm_to_analyzer" {
  name        = "${var.name}-alarm-to-analyzer"
  description = "Invoke the analyzer when the demo-shop alarm enters ALARM."

  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    resources     = [aws_cloudwatch_metric_alarm.db_errors.arn]
    detail = {
      state = { value = ["ALARM"] }
    }
  })
}

resource "aws_cloudwatch_event_target" "analyzer" {
  rule = aws_cloudwatch_event_rule.alarm_to_analyzer.name
  arn  = aws_lambda_function.analyzer.arn

  retry_policy {
    maximum_retry_attempts       = 2
    maximum_event_age_in_seconds = 900
  }
}

resource "aws_lambda_permission" "eventbridge_invoke_analyzer" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.analyzer.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.alarm_to_analyzer.arn
}
