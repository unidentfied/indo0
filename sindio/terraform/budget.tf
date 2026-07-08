# ============================================================
# Sindio — AWS Budget Alerts
# ============================================================

resource "aws_budgets_budget" "sindio_monthly" {
  name              = "sindio-${var.environment}-monthly"
  budget_type       = "COST"
  limit_amount      = var.environment == "prod" ? 1000 : 500
  limit_unit        = "USD"
  time_period_start = "2024-01-01_00:00"
  time_unit         = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$sindio"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["ops@sindio.net"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["ops@sindio.net", "finance@sindio.net"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 120
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["ops@sindio.net", "finance@sindio.net", "cto@sindio.net"]
  }
}

# Cost anomaly detection (requires Cost Explorer to be enabled on the account)
# If you get "User not enabled for cost explorer access", uncomment after enabling
# in the AWS Billing console: https://console.aws.amazon.com/billing/home#/preferences

# resource "aws_ce_anomaly_monitor" "sindio_service" {
#   name              = "sindio-${var.environment}-service-monitor"
#   monitor_type      = "DIMENSIONAL"
#   monitor_dimension = "SERVICE"
# }

# resource "aws_ce_anomaly_subscription" "sindio_alerts" {
#   name      = "sindio-${var.environment}-anomaly-alerts"
#   frequency = "IMMEDIATE"

#   monitor_arn_list = [aws_ce_anomaly_monitor.sindio_service.arn]

#   subscriber {
#     type    = "EMAIL"
#     address = "ops@sindio.net"
#   }

#   threshold_expression {
#     dimension {
#       key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
#       match_options = ["GREATER_THAN_OR_EQUAL"]
#       values        = ["100"]
#     }
#   }
# }
