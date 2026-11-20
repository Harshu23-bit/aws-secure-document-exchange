# ==========================================
# VPC
# ==========================================

resource "aws_vpc" "main" {
  cidr_block = "10.20.0.0/16"

  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name        = "cloudsec-vpc"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}

# ==========================================
# INTERNET GATEWAY
# ==========================================

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "cloudsec-igw"
  }
}

# ==========================================
# PUBLIC SUBNETS
# ==========================================

resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.1.0/24"
  availability_zone       = "ap-south-1a"
  map_public_ip_on_launch = false

  tags = {
    Name = "cloudsec-public-a"
    Tier = "public"
  }
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.2.0/24"
  availability_zone       = "ap-south-1b"
  map_public_ip_on_launch = false

  tags = {
    Name = "cloudsec-public-b"
    Tier = "public"
  }
}

# ==========================================
# PRIVATE SUBNETS
# ==========================================

resource "aws_subnet" "private_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.11.0/24"
  availability_zone       = "ap-south-1a"
  map_public_ip_on_launch = false

  tags = {
    Name = "cloudsec-private-a"
    Tier = "private"
  }
}

resource "aws_subnet" "private_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.12.0/24"
  availability_zone       = "ap-south-1b"
  map_public_ip_on_launch = false

  tags = {
    Name = "cloudsec-private-b"
    Tier = "private"
  }
}

# ==========================================
# PUBLIC ROUTE TABLE
# ==========================================

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "cloudsec-public-rt"
  }
}

# ==========================================
# PRIVATE ROUTE TABLE
# ==========================================

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "cloudsec-private-rt"
  }
}

# ==========================================
# PUBLIC ROUTE TABLE ASSOCIATIONS
# ==========================================

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

# ==========================================
# PRIVATE ROUTE TABLE ASSOCIATIONS
# ==========================================

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

# ==========================================
# OUTPUTS
# ==========================================

output "vpc_id" {
  description = "ID of the Cloud Security VPC."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets."
  value = [
    aws_subnet.public_a.id,
    aws_subnet.public_b.id
  ]
}

output "private_subnet_ids" {
  description = "IDs of the private subnets."
  value = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id
  ]
}

# Restrict the VPC default security group
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id

  ingress = []
  egress  = []

  tags = {
    Name    = "cloudsec-default-deny"
    Project = "AWS-Secure-Infrastructure"
  }
}

# VPC FLOW LOGS
resource "aws_flow_log" "main" {
  log_destination      = aws_s3_bucket.vpc_flow_logs.arn
  log_destination_type = "s3"
  traffic_type         = "ALL"
  vpc_id               = aws_vpc.main.id

  tags = {
    Name        = "cloudsec-vpc-flow-logs"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }

  depends_on = [
    aws_s3_bucket_policy.vpc_flow_logs
  ]
}
