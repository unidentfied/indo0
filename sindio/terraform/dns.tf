# ============================================================
# Sindio — Route53 + ACM SSL Certificate
# ============================================================

# Route53 Hosted Zone
resource "aws_route53_zone" "sindio" {
  name = var.custom_domain != "" ? var.custom_domain : "sindio.urban"

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# ACM Certificate (us-east-1 required for CloudFront / ALB)
resource "aws_acm_certificate" "sindio" {
  provider = aws.us_east_1

  domain_name               = var.custom_domain != "" ? var.custom_domain : "sindio.urban"
  subject_alternative_names = ["*.${var.custom_domain != "" ? var.custom_domain : "sindio.urban"}"]
  validation_method         = "DNS"

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# DNS validation records
resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.sindio.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  zone_id = aws_route53_zone.sindio.zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 60
}

# Certificate validation
resource "aws_acm_certificate_validation" "sindio" {
  provider = aws.us_east_1

  certificate_arn         = aws_acm_certificate.sindio.arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

# ALB Security Group
resource "aws_security_group" "alb" {
  name        = "sindio-${var.environment}-alb"
  description = "ALB for Sindio API"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# Application Load Balancer
resource "aws_lb" "sindio" {
  name               = "sindio-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = module.vpc.public_subnets

  enable_deletion_protection = var.environment == "prod"

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# Target group (empty; targets registered by AWS Load Balancer Controller or manually)
resource "aws_lb_target_group" "sindio" {
  name     = "sindio-${var.environment}-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = module.vpc.vpc_id

  health_check {
    path                = "/health"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# HTTPS Listener
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.sindio.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.sindio.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.sindio.arn
  }
}

# ALB DNS record (points to ALB, NOT the Kubernetes API endpoint)
resource "aws_route53_record" "api" {
  zone_id = aws_route53_zone.sindio.zone_id
  name    = var.custom_domain != "" ? var.custom_domain : "sindio.urban"
  type    = "A"

  alias {
    name                   = aws_lb.sindio.dns_name
    zone_id                = aws_lb.sindio.zone_id
    evaluate_target_health = true
  }
}

# Netlify CNAME for frontend
resource "aws_route53_record" "frontend" {
  zone_id = aws_route53_zone.sindio.zone_id
  name    = "app"
  type    = "CNAME"
  ttl     = 300
  records = ["sindio.netlify.app"]  # Update with actual Netlify domain
}

variable "custom_domain" {
  type    = string
  default = ""
}

# Additional AWS provider for us-east-1 (ACM requirement)
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

output "nameservers" {
  value = aws_route53_zone.sindio.name_servers
}

output "certificate_arn" {
  value = aws_acm_certificate.sindio.arn
}
