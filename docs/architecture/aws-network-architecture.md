# AWS Network Architecture

**Project:** AWS Secure Infrastructure Blueprint  
**Document:** AWS Network Architecture  
**Version:** 2.1  
**Review date:** 20 November 2026  
**Status:** Terraform implementation locally validated; AWS deployment and live network validation pending.

---

## 1. Objective

The objective of this architecture is to establish a segmented AWS network environment for a secure multi-tenant document submission and review application.

The architecture separates the public API entry point from private application infrastructure and restricts communication between components through security groups, private subnets, and controlled service connectivity.

The primary security objectives are:

- Avoid direct internet exposure of application compute resources.
- Provide a controlled public API entry point.
- Restrict internal communication to required network paths.
- Support private AWS service connectivity.
- Enable network traffic monitoring.
- Avoid unnecessary NAT Gateway costs.
- Support future availability and resilience improvements.

## 2. AWS Region and Availability Zones

| Property | Configuration |
|---|---|
| AWS Region | `ap-south-1` |
| Availability Zone A | `ap-south-1a` |
| Availability Zone B | `ap-south-1b` |
| VPC CIDR | `10.20.0.0/16` |

The VPC spans two Availability Zones to provide subnet-level separation and support future multi-AZ deployment.

The presence of two Availability Zones does not by itself guarantee application high availability.

## 3. VPC Configuration

### 3.1 VPC

The project uses the following VPC configuration:

- CIDR: `10.20.0.0/16`
- DNS support enabled.
- DNS hostnames enabled.
- Internet Gateway attached.
- Separate public and private route tables.
- Security groups configured for component-level traffic restrictions.

### 3.2 Subnet Allocation

| Subnet | Availability Zone | CIDR | Intended purpose |
|---|---|---|---|
| Public-A | ap-south-1a | 10.20.1.0/24 | Public subnet tier and internet-gateway routing |
| Public-B | ap-south-1b | 10.20.2.0/24 | Public subnet tier and internet-gateway routing |
| Private-A | ap-south-1a | 10.20.11.0/24 | Application compute and private service connectivity |
| Private-B | ap-south-1b | 10.20.12.0/24 | Application compute and private service connectivity |

All four subnets are configured without automatic public IPv4 address assignment.

The application EC2 instances are placed in private subnets.

The ALB is internal and is not intended to be directly accessible from the internet.

## 4. Network Architecture Components

### 4.1 Core Networking

The Terraform configuration defines:

- Amazon VPC.
- Internet Gateway.
- Two public subnets.
- Two private subnets.
- Public route table.
- Private route table.
- Route table associations.
- Security groups.
- VPC Flow Logs.

### 4.2 Application Ingress

The application ingress architecture consists of:

- Regional Amazon API Gateway REST API.
- AWS WAF Web ACL associated with API Gateway.
- Amazon Cognito authorization.
- API Gateway VPC Link V2.
- Internal Application Load Balancer.
- Private EC2 Auto Scaling Group.

API Gateway provides the public application endpoint.

The internal ALB is reachable through the configured VPC Link rather than through direct public internet access.

### 4.3 Private AWS Service Connectivity

The following VPC endpoints are configured:

| Endpoint | Type | Purpose |
|---|---|---|
| SSM | Interface | Systems Manager service access |
| SSM Messages | Interface | Systems Manager session communication |
| ECR API | Interface | Private ECR API access |
| ECR DKR | Interface | Private ECR registry access |
| S3 | Gateway | Private S3 service connectivity |
| DynamoDB | Gateway | Private DynamoDB service connectivity |

The interface endpoints are currently configured in Private-A.

The S3 and DynamoDB gateway endpoints provide private service connectivity through the relevant route table configuration.

These endpoints reduce dependence on public internet routing for supported AWS service operations.

## 5. Application Traffic Flow

### 5.1 External API Request

The intended application request path is:

1. External client sends an HTTPS request to the Regional API Gateway endpoint.
2. API Gateway evaluates the configured Cognito authorization requirements.
3. AWS WAF evaluates the request against the associated Web ACL.
4. API Gateway forwards the request through VPC Link V2.
5. VPC Link connects to the internal ALB.
6. The ALB forwards the request to the application target group.
7. The EC2 application instance receives traffic on TCP 8080.
8. FastAPI performs its own authentication and authorization checks.
9. The application accesses the required private AWS services.

API Gateway and FastAPI independently enforce authentication-related controls.

Backend authorization remains authoritative for tenant and role boundaries.

### 5.2 Internal Network Flow

The relevant internal communication path is:

| Source | Destination | Protocol / Port | Purpose |
|---|---|---|---|
| VPC Link security group | Internal ALB security group | TCP 80 | API request forwarding |
| Internal ALB | Application security group | TCP 8080 | Backend application traffic |
| EC2 application instances | S3 | AWS service connectivity through gateway endpoint | Document and application object access |
| EC2 application instances | DynamoDB | AWS service connectivity through gateway endpoint | Application data access |
| EC2 instances | ECR | HTTPS through configured endpoints | Container image retrieval |
| EC2 instances | Systems Manager | HTTPS through configured endpoints | Private administration |

The internal ALB listener uses HTTP on port 80 and forwards to the application target group using HTTP on port 8080.

Internal transport encryption remains a hardening opportunity.

## 6. Security Group Design

Security groups implement the network-level communication boundaries.

### 6.1 VPC Link Security Group

- Egress TCP 80 to the internal ALB security group.
- No unnecessary unrestricted outbound access.

### 6.2 Internal ALB Security Group

Ingress:

- TCP 80 only from the VPC Link security group.

Egress:

- TCP 8080 only to the application security group.

### 6.3 Application Security Group

Ingress:

- TCP 8080 only from the internal ALB security group.

Egress:

- No unrestricted default egress.
- Required outbound access is explicitly defined.

### 6.4 Default Security Group

The VPC default security group is configured with:

- Empty ingress rules.
- Empty egress rules.

### 6.5 Security Boundary

The intended network trust relationship is:

```text
External Client
      |
      | HTTPS
      v
Regional API Gateway
      |
      +---- AWS WAF
      |
      +---- Cognito Authorization
      |
      v
VPC Link V2
      |
      | TCP 80
      v
Internal ALB
      |
      | TCP 8080
      v
Private EC2 Application Instances
      |
      +---- S3 Gateway Endpoint
      |
      +---- DynamoDB Gateway Endpoint
      |
      +---- ECR Interface Endpoints
      |
      +---- Systems Manager Endpoints
```

The ALB and EC2 instances do not receive direct public application ingress.

## 7. Routing Architecture

### 7.1 Public Route Table

The public route table includes:

- VPC-local route.
- Default route `0.0.0.0/0` through the Internet Gateway.

The public subnet tier is defined in the VPC architecture.

It does not mean that the application ALB or EC2 instances are internet-facing.

### 7.2 Private Route Table

The private route table includes:

- VPC-local routing.
- Required gateway endpoint routes.

There is no default route through a NAT Gateway.

### 7.3 NAT Gateway

No NAT Gateway is configured.

This reduces recurring hourly and data-processing charges.

However, private instances cannot automatically access arbitrary public internet destinations.

Package installation, bootstrap operations, and any external dependency retrieval must therefore be validated against the available private connectivity design.

## 8. Private Administration

Systems Manager is the intended administrative access mechanism for EC2 instances.

The architecture includes:

- EC2 instance role for Systems Manager.
- SSM interface endpoint.
- SSM Messages interface endpoint.
- Private application instances.
- No requirement for unrestricted inbound SSH.

This avoids exposing administrative SSH access directly to the internet.

Actual Session Manager connectivity must be validated after deployment.

## 9. Network Monitoring and Logging

### 9.1 VPC Flow Logs

VPC Flow Logs are configured with:

- Traffic type: `ALL`.
- S3 delivery destination.
- Private S3 bucket.
- Server-side encryption.
- Bucket versioning.
- Lifecycle expiration for current and noncurrent objects.
- Incomplete multipart upload cleanup.

The Flow Logs configuration provides network traffic metadata for investigation and troubleshooting.

Flow Logs do not capture the full contents of application network packets.

### 9.2 Load Balancer Access Logs

The internal ALB is configured for S3 access logging.

The logging destination is private and uses the project's configured storage protections.

### 9.3 Logging Limitations

- Flow Log delivery has not been validated against deployed AWS resources.
- S3 server access logging is best-effort rather than real-time.
- Network traffic metadata does not replace application-level audit events.
- Log delivery, retention, and access permissions require live validation.

## 10. Application Compute Placement

The application runs on EC2 instances in private subnets.

### 10.1 Auto Scaling Configuration

The Auto Scaling Group is configured with:

| Property | Configuration |
|---|---|
| Minimum capacity | 0 or 1 depending on image digest configuration |
| Desired capacity | 0 or 1 depending on image digest configuration |
| Maximum capacity | 2 |
| Availability Zones | Two configured private subnet AZs |
| Health-check grace period | 300 seconds |

When no application image digest is configured, the initial minimum and desired capacity are zero.

When a valid image digest is configured, the minimum and desired capacity become one.

This avoids launching an instance that cannot retrieve a valid application image.

The maximum capacity of two does not establish automatic scaling policies or guarantee multi-instance availability.

### 10.2 EC2 Security Configuration

The application instances use:

- Amazon Linux 2023.
- IMDSv2 required.
- Metadata response hop limit of one.
- Encrypted gp3 root volume.
- Private network interfaces.
- No public IPv4 address assignment.
- Systems Manager instance role.
- Docker-based application runtime.

### 10.3 Container Network Exposure

The application container publishes TCP 8080 on the instance network interface.

Network reachability is restricted by the application security group, which permits access only from the internal ALB security group.

Container port binding does not independently make the application publicly accessible.

## 11. Availability and Resilience

The architecture defines two public and two private subnets across two Availability Zones.

However, several limitations remain:

- The initial application capacity is one instance when an image digest is configured.
- The maximum ASG capacity is two, but scaling policies are not established by this setting alone.
- Interface endpoints currently exist in only one private subnet.
- No NAT Gateway is configured.
- Internal transport currently uses HTTP.
- Live failover and Availability Zone impairment behavior have not been tested.

Multi-AZ subnet placement should not be described as proof of high availability.

## 12. Cost Considerations

The network architecture intentionally avoids unnecessary always-on resources.

### 12.1 Cost-Sensitive Design Decisions

- No NAT Gateway.
- S3 Gateway Endpoint rather than NAT-based S3 access.
- DynamoDB Gateway Endpoint.
- Interface endpoints limited to selected AWS services.
- Initial application capacity can remain zero until a valid image digest is configured.
- No unnecessary public application load balancer.

### 12.2 Potential Costs

Potential network-related costs include:

- Interface endpoint hourly charges.
- Interface endpoint data processing charges.
- ALB hourly and capacity-related charges.
- API Gateway requests.
- WAF usage.
- S3 storage and request charges.
- VPC Flow Logs storage and delivery.
- Data transfer charges.

S3 and DynamoDB gateway endpoints do not have an hourly endpoint charge.

Actual costs depend on deployment, region, usage, and service pricing.

## 13. Known Limitations and Hardening Requirements

| ID | Limitation | Impact | Required action |
|---|---|---|---|
| NET-01 | No NAT Gateway | Arbitrary internet egress is unavailable from private subnets. | Validate package and bootstrap connectivity. |
| NET-02 | Interface endpoints in one private subnet | Reduced endpoint availability across AZs. | Evaluate multi-AZ endpoint placement. |
| NET-03 | Internal HTTP transport | Internal network traffic is not encrypted at the ALB-to-target path. | Evaluate TLS support and certificate management. |
| NET-04 | Initial application capacity of one | No guaranteed instance-level redundancy. | Validate desired capacity and scaling strategy. |
| NET-05 | WAF URI scope-down requires verification | Rate-limit rule coverage may differ from the intended API paths. | Verify deployed URI behavior. |
| NET-06 | No live network validation | Terraform configuration does not prove deployed enforcement. | Validate actual routes, endpoints, and security groups. |
| NET-07 | Flow Log delivery unverified | Network monitoring is not yet operationally demonstrated. | Validate delivery and retention in AWS. |

These items are deployment dependencies or hardening opportunities, not automatically confirmed vulnerabilities.

## 14. Deployment and Validation Status

### 14.1 Local Infrastructure Validation

The Terraform implementation has undergone local formatting and validation.

Checkov scanning has also been performed against the reviewed Terraform configuration.

Latest recorded Checkov result:

- 640 passed.
- 0 failed.
- 67 skipped.

The previously identified DynamoDB GSI `hash_key`/`range_key` deprecation warning was resolved by migrating the affected GSI to the provider's `key_schema` configuration. The latest recorded `terraform validate` completed successfully without that warning.

### 14.2 AWS Deployment Status

No AWS infrastructure has been deployed.

The Terraform state contains zero managed resources.

Consequently, the following remain unverified:

- Actual VPC and subnet deployment.
- Route table behavior.
- Security group enforcement.
- VPC Link connectivity.
- Internal ALB reachability.
- EC2 bootstrap and image retrieval.
- SSM Session Manager access.
- VPC endpoint connectivity.
- VPC Flow Logs delivery.
- ALB access log delivery.
- WAF rate-limit enforcement.

### 14.3 Required Post-Deployment Tests

After an authorized deployment, perform the following validation:

1. Confirm the VPC CIDR and subnet allocations.
2. Confirm public and private route table associations.
3. Verify the private route table has no unintended default internet route.
4. Inspect security group ingress and egress rules.
5. Confirm EC2 instances have no public IP addresses.
6. Verify the ALB is internal.
7. Confirm API Gateway can reach the ALB through VPC Link V2.
8. Verify that direct public access to the ALB and EC2 application port is unavailable.
9. Test S3 and DynamoDB gateway endpoint connectivity.
10. Test ECR image retrieval through the configured private endpoints.
11. Test Systems Manager connectivity.
12. Verify VPC Flow Logs and ALB access log delivery.
13. Test the WAF rate-based rule against the actual API URI.
14. Review network behavior during controlled failure scenarios.

## 15. Conclusion

The network architecture separates the public API entry point from private application infrastructure.

Regional API Gateway, AWS WAF, Cognito authorization, VPC Link V2, the internal ALB, private EC2 instances, security groups, and private AWS service endpoints form the primary network security boundaries.

The design avoids direct public exposure of application compute resources and does not depend on a NAT Gateway.

Terraform implementation and local validation are complete for the reviewed configuration. AWS deployment, live connectivity testing, and operational network validation remain outstanding.

The architecture should be considered implemented locally, with deployment verification still required.
