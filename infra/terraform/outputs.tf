output "cluster_enabled" {
  value = var.enable_cluster
}

output "cluster_name" {
  value = local.cluster_name
}

output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${local.cluster_name}"
}

output "slack_interactivity_url" {
  description = "Paste into Slack app -> Interactivity & Shortcuts -> Request URL."
  value       = aws_lambda_function_url.executor.function_url
}

output "alarm_name" {
  value = aws_cloudwatch_metric_alarm.db_errors.alarm_name
}

output "app_log_group" {
  value = aws_cloudwatch_log_group.application.name
}

output "secret_arns" {
  value = { for k, s in aws_secretsmanager_secret.this : k => s.arn }
}

output "analyzer_function" {
  value = aws_lambda_function.analyzer.function_name
}

output "executor_function" {
  value = aws_lambda_function.executor.function_name
}
