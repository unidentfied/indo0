# ============================================================
# Sindio — Terraform: AWS infrastructure
# ============================================================
# Apply:
#   cd terraform && terraform init && terraform plan -var-file=dev.tfvars && terraform apply
#
# Resources:
#   EKS cluster (3 nodes, t3.large dev / c5.2xlarge sim workers)
#   RDS PostgreSQL (db.t3.micro dev / db.r6g.large prod + read replica)
#   ElastiCache Redis (cache.t3.micro)
#   OpenSearch Service (t3.small.search dev / r6g.large.search prod)
#   S3 bucket for model checkpoints + simulation outputs
#   ECR repositories for each service
# ============================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = ">= 1.14.0"
    }
  }
  backend "s3" {
    bucket         = "sindio-tfstate"
    key            = "terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "sindio-tfstate-lock"
  }
}

provider "aws" {
  region = var.aws_region
}

# ============================================================
# Variables
# ============================================================

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region for all resources"
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "dev | prod"
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod."
  }
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

# ============================================================
# VPC + Subnets
# ============================================================

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.5"

  name = "sindio-${var.environment}"
  cidr = var.vpc_cidr

  azs             = ["${var.aws_region}a", "${var.aws_region}b", "${var.aws_region}c"]
  private_subnets = [for i in range(3) : cidrsubnet(var.vpc_cidr, 8, i + 1)]
  public_subnets  = [for i in range(3) : cidrsubnet(var.vpc_cidr, 8, i + 101)]

  enable_nat_gateway = var.environment == "prod"
  single_nat_gateway = var.environment == "dev"

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# ============================================================
# EKS Cluster
# ============================================================

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "19.21"

  cluster_name    = "sindio-${var.environment}"
  cluster_version = "1.32"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true

  eks_managed_node_group_defaults = {
    ami_type = "AL2_x86_64"
  }

  eks_managed_node_groups = {
    # General-purpose nodes (API, RAG, frontend)
    general = {
      instance_types = ["t3.micro"]
      min_size       = 1
      max_size       = 4
      desired_size   = 1
      labels = {
        role = "general"
      }
    }
    # Simulation workers
    simulator = {
      instance_types = ["t3.micro"]
      min_size       = 1
      max_size       = 4
      desired_size   = 1
      labels = {
        role = "simulator"
      }
    }
  }

  node_security_group_additional_rules = {
    ingress_self_all = {
      description = "Allow node-to-node communication"
      protocol    = "-1"
      from_port   = 0
      to_port     = 0
      type        = "ingress"
      self        = true
    }
  }

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# ============================================================
# EKS Cluster Autoscaler — deployed manually after cluster creation
# via helm or kubectl. See docs/cluster-autoscaler.md
# ============================================================

# ============================================================
# RDS PostgreSQL (with read replica in prod)
# ============================================================

module "rds" {
  source  = "terraform-aws-modules/rds/aws"
  version = "6.3"

  identifier = "sindio-${var.environment}"

  engine         = "postgres"
  engine_version = "16.3"
  family         = "postgres16"

  instance_class    = "db.t3.micro"
  allocated_storage = 20
  storage_encrypted = true

  db_name     = "sindio"
  username    = "sindio_user"
  port        = 5432
  manage_master_user_password = true

  vpc_security_group_ids = [module.vpc.default_security_group_id]
  subnet_ids             = module.vpc.private_subnets

  backup_retention_period = 1
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:05:00-sun:06:00"

  deletion_protection = false

  parameters = [
    { name = "shared_preload_libraries", value = "pg_stat_statements", apply_method = "pending-reboot" },
    { name = "rds.force_ssl", value = "1", apply_method = "pending-reboot" },
  ]

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# Read replica (prod only)
resource "aws_db_instance" "replica" {
  count = var.environment == "prod" ? 1 : 0

  identifier          = "sindio-${var.environment}-replica"
  replicate_source_db = module.rds.db_instance_identifier
  instance_class      = "db.t3.micro"
  vpc_security_group_ids = [module.vpc.default_security_group_id]
  publicly_accessible = false

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# ============================================================
# ElastiCache Redis (Celery broker + agent state)
# ============================================================

resource "aws_elasticache_subnet_group" "redis" {
  name       = "sindio-${var.environment}-redis"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "sindio-${var.environment}"
  engine               = "redis"
  node_type            = var.environment == "prod" ? "cache.t3.medium" : "cache.t3.micro"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.redis.name
  security_group_ids   = [module.vpc.default_security_group_id]

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# ============================================================
# OpenSearch Service (hybrid text search)
# ============================================================

resource "aws_opensearch_domain" "sindio" {
  domain_name = "sindio-${var.environment}"

  engine_version = "OpenSearch_2.11"

  cluster_config {
    instance_type  = var.environment == "prod" ? "r6g.large.search" : "t3.small.search"
    instance_count = var.environment == "prod" ? 3 : 1
  }

  ebs_options {
    ebs_enabled = true
    volume_size = var.environment == "prod" ? 100 : 20
    volume_type = "gp3"
  }

  vpc_options {
    subnet_ids         = [module.vpc.private_subnets[0]]
    security_group_ids = [module.vpc.default_security_group_id]
  }

  encrypt_at_rest {
    enabled = true
  }
  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  advanced_security_options {
    enabled                        = false  # dev; set true + master user for prod
    internal_user_database_enabled = false
  }

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# ============================================================
# S3 — Model checkpoints + simulation outputs
# ============================================================

resource "aws_s3_bucket" "models" {
  bucket = "sindio-${var.environment}-models"

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

resource "aws_s3_bucket_versioning" "models" {
  bucket = aws_s3_bucket.models.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "models" {
  bucket = aws_s3_bucket.models.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket" "simulations" {
  bucket = "sindio-${var.environment}-simulations"

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "simulations" {
  bucket = aws_s3_bucket.simulations.id
  rule {
    id     = "expire-old-simulations"
    status = "Enabled"
    filter {
      prefix = ""
    }
    expiration {
      days = var.environment == "prod" ? 90 : 7
    }
  }
}

# ============================================================
# ECR repositories
# ============================================================

resource "aws_ecr_repository" "repos" {
  for_each = toset(["sindio-api", "sindio-simulator", "sindio-rag", "sindio-frontend"])

  name                 = each.key
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Environment = var.environment
    Project     = "sindio"
  }
}

# ============================================================
# IAM Roles for Service Accounts (IRSA) — Pod → AWS service access
# ============================================================

# IAM policy for RDS access (read/write to Sindio database)
resource "aws_iam_policy" "rds_access" {
  name        = "sindio-${var.environment}-rds-access"
  description = "Allow Sindio pods to connect to RDS PostgreSQL"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["rds-db:connect"]
        Resource = [
          "arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${module.rds.db_instance_resource_id}/sindio_user"
        ]
      }
    ]
  })
}

# IAM policy for ElastiCache access
resource "aws_iam_policy" "elasticache_access" {
  name        = "sindio-${var.environment}-elasticache-access"
  description = "Allow Sindio pods to connect to ElastiCache Redis"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["elasticache:Connect"]
        Resource = [aws_elasticache_cluster.redis.arn]
      }
    ]
  })
}

# IAM policy for OpenSearch access
resource "aws_iam_policy" "opensearch_access" {
  name        = "sindio-${var.environment}-opensearch-access"
  description = "Allow Sindio pods to read/write to OpenSearch domain"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "es:ESHttpGet",
          "es:ESHttpPut",
          "es:ESHttpPost",
          "es:ESHttpDelete",
          "es:ESHttpHead",
        ]
        Resource = "${aws_opensearch_domain.sindio.arn}/*"
      }
    ]
  })
}

# IAM policy for S3 access (model checkpoints + simulation outputs)
resource "aws_iam_policy" "s3_access" {
  name        = "sindio-${var.environment}-s3-access"
  description = "Allow Sindio pods to read/write S3 buckets"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
        Resource = [
          aws_s3_bucket.models.arn,
          "${aws_s3_bucket.models.arn}/*",
          aws_s3_bucket.simulations.arn,
          "${aws_s3_bucket.simulations.arn}/*",
        ]
      }
    ]
  })
}

# IRSA role for backend services (attached to K8s service accounts)
resource "aws_iam_role" "sindio_backend" {
  name = "sindio-${var.environment}-backend-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = module.eks.oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${module.eks.oidc_provider}:sub" : "system:serviceaccount:sindio:sindio-backend"
          }
        }
      }
    ]
  })
}


resource "aws_iam_role_policy_attachment" "backend_rds" {
  role       = aws_iam_role.sindio_backend.name
  policy_arn = aws_iam_policy.rds_access.arn
}

resource "aws_iam_role_policy_attachment" "backend_redis" {
  role       = aws_iam_role.sindio_backend.name
  policy_arn = aws_iam_policy.elasticache_access.arn
}

resource "aws_iam_role_policy_attachment" "backend_opensearch" {
  role       = aws_iam_role.sindio_backend.name
  policy_arn = aws_iam_policy.opensearch_access.arn
}

resource "aws_iam_role_policy_attachment" "backend_s3" {
  role       = aws_iam_role.sindio_backend.name
  policy_arn = aws_iam_policy.s3_access.arn
}

data "aws_caller_identity" "current" {}

# ============================================================
# Outputs
# ============================================================

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "rds_endpoint" {
  value = module.rds.db_instance_address
}

output "redis_endpoint" {
  value = aws_elasticache_cluster.redis.cache_nodes[0].address
}

output "opensearch_endpoint" {
  value = aws_opensearch_domain.sindio.endpoint
}

output "ecr_repository_urls" {
  value = {
    for k, v in aws_ecr_repository.repos : k => v.repository_url
  }
}

output "models_bucket" {
  value = aws_s3_bucket.models.bucket
}

output "simulations_bucket" {
  value = aws_s3_bucket.simulations.bucket
}
