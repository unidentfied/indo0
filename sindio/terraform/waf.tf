# ============================================================
# Sindio — AWS WAF Rules
# ============================================================

resource "aws_wafv2_web_acl" "sindio_api" {
  name        = "sindio-${var.environment}-api-waf"
  description = "WAF rules for Sindio API"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # SQL Injection protection
  rule {
    name     = "SQLInjectionProtection"
    priority = 1

    action {
      block {}
    }

    statement {
      or_statement {
        statement {
          sqli_match_statement {
            field_to_match {
              body {}
            }
            text_transformation {
              priority = 0
              type     = "URL_DECODE"
            }
            text_transformation {
              priority = 1
              type     = "HTML_ENTITY_DECODE"
            }
          }
        }
        statement {
          sqli_match_statement {
            field_to_match {
              query_string {}
            }
            text_transformation {
              priority = 0
              type     = "URL_DECODE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "SQLInjectionProtection"
      sampled_requests_enabled   = true
    }
  }

  # XSS protection
  rule {
    name     = "XSSProtection"
    priority = 2

    action {
      block {}
    }

    statement {
      xss_match_statement {
        field_to_match {
          body {}
        }
        text_transformation {
          priority = 0
          type     = "URL_DECODE"
        }
        text_transformation {
          priority = 1
          type     = "HTML_ENTITY_DECODE"
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "XSSProtection"
      sampled_requests_enabled   = true
    }
  }

  # Rate limiting (10,000 requests per 5 min)
  rule {
    name     = "RateLimit"
    priority = 3

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 10000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimit"
      sampled_requests_enabled   = true
    }
  }

  # Geographic restriction (allow East Africa + major markets)
  rule {
    name     = "GeoRestriction"
    priority = 4

    action {
      block {}
    }

    statement {
      geo_match_statement {
        country_codes = ["KE", "TZ", "UG", "RW", "ET", "ZA", "US", "GB", "DE"]
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "GeoRestriction"
      sampled_requests_enabled   = true
    }
  }

  # Managed rule: AWS Common Rules
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 5

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesCommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "sindio-${var.environment}-api-waf"
    sampled_requests_enabled   = true
  }
}

# Attach WAF to the ALB so rules are actually enforced
resource "aws_wafv2_web_acl_association" "sindio_alb" {
  resource_arn = aws_lb.sindio.arn
  web_acl_arn  = aws_wafv2_web_acl.sindio_api.arn
}
