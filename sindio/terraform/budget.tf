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
    tag_key    = "Project"
    tag_values = ["sindio"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["ops@sindio.urban"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["ops@sindio.urban", "finance@sindio.urban"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 120
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["ops@sindio.urban", "finance@sindio.urban", "cto@sindio.urban"]
  }
}

# Cost anomaly detection
resource "aws_ce_anomaly_monitor" "sindio_service" {
  name              = "sindio-${var.environment}-service-monitor"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "sindio_alerts" {
  name      = "sindio-${var.environment}-anomaly-alerts"
  threshold = 100  # Alert on $100+ anomalies
  frequency = "IMMEDIATE"

  monitor_arn_list = [aws_ce_anomaly_monitor.sindio_service.arn]

  subscriber {
    type    = "EMAIL"
    address = "ops@sindio.urban"
  }
}
