# AWS Secure Infrastructure Blueprint

A security-focused, multi-tenant document submission and review platform built using AWS, FastAPI, React, Terraform, and automated security controls.

The project demonstrates practical cloud security engineering across application security, identity and access management, infrastructure as code, secure document storage, serverless lifecycle management, container security, and CI/CD security.

> **Project status:** Local implementation and validation in progress. AWS infrastructure has not been deployed. GitHub Actions workflows have passed local validation but have not yet undergone their first remote execution.

---

## 1. Project Objectives

The project aims to demonstrate how to design and implement a secure AWS-hosted application with:

- Strong tenant isolation and role-based authorization.
- Cognito-based authentication and JWT validation.
- Secure document uploads and downloads.
- Encryption at rest and controlled access to stored documents.
- Auditable submission and review workflows.
- Automated document lifecycle management.
- Infrastructure as Code using Terraform.
- Security-focused CI/CD and automated scanning.
- Container hardening and vulnerability assessment.

The implementation prioritizes least privilege, defense in depth, explicit authorization checks, and secure failure handling.

## 2. Architecture Overview

The platform follows a multi-tier architecture.

### Application layer

- **Frontend:** React, TypeScript, Vite.
- **Backend:** Python, FastAPI.
- **Authentication:** Amazon Cognito.
- **Authorization:** Tenant-scoped role and membership checks.

### AWS infrastructure

- Amazon VPC with public and private subnets.
- API Gateway REST API.
- Internal Application Load Balancer.
- Amazon EC2 Auto Scaling Group running the containerized application behind an internal Application Load Balancer.
- Amazon DynamoDB.
- Amazon S3.
- AWS KMS.
- AWS WAF.
- AWS CloudTrail.
- Amazon CloudWatch and SNS.
- AWS Lambda and EventBridge Scheduler.

The infrastructure is defined using Terraform in `terraform/environments/dev/`.

### High-level request flow

1. A user authenticates through Amazon Cognito.
2. The frontend obtains an access token.
3. The backend validates the token and its required scope.
4. Membership authorization establishes the user's tenant and role.
5. Application services enforce tenant and resource-level authorization.
6. DynamoDB stores application metadata and workflow state.
7. S3 stores uploaded document objects.
8. Background Lambda functions handle document lifecycle operations.
9. Audit events and operational logs provide traceability.

## 3. Application Roles

The platform implements three application roles.

| Role | Capabilities |
|---|---|
| SUBMITTER | Create submissions, upload supported documents, view own submissions. |
| REVIEWER | Review tenant-scoped submissions, access eligible documents, perform permitted workflow transitions. |
| TENANT_ADMIN | Manage tenant memberships and inspect tenant audit events. |

Tenant administrators do not automatically receive access to document contents.

Authorization is enforced by the backend. Frontend route protection and role-based UI visibility are usability controls, not security boundaries.

## 4. Security Architecture

### Authentication

- Cognito access-token authentication.
- RS256 JWT signature verification.
- Issuer, expiration, token type, client ID and required scope validation.
- JWKS synchronization through a dedicated Lambda function.

### Authorization and tenant isolation

- Strongly consistent membership reads.
- Explicit tenant and user identity validation.
- Resource ownership checks.
- Transaction-level reviewer authorization during workflow transitions.
- Conditional DynamoDB writes to protect state transitions.
- Tenant-scoped audit and submission access.

### Document security

- Server-generated S3 object keys.
- Short-lived presigned upload and download requests.
- Supported document types: PDF, JPEG and PNG.
- Maximum document size: 10 MiB.
- SSE-KMS encryption and exact KMS key validation.
- Exact S3 object version verification.
- Document ownership and workflow-state checks.
- Automated cleanup of expired and unaccepted document versions.

File signature checks provide basic content validation. They are not a replacement for malware scanning or full document sanitization.

### Infrastructure security

- Private application networking.
- Security-group-based traffic restrictions.
- Encryption using AWS KMS.
- S3 public-access blocking.
- CloudTrail and CloudWatch logging.
- WAF protection.
- Scoped IAM permissions.
- Terraform security scanning with Checkov and TFLint.

## 5. Document Lifecycle Automation

Five Lambda functions implement background and security-sensitive lifecycle operations.

| Function | Responsibility |
|---|---|
| JWKS Sync | Synchronizes Cognito public signing keys. |
| Document Expiry | Expires pending document upload reservations. |
| Document Cleanup | Removes expired document object versions. |
| Document Finalization | Removes metadata after successful object cleanup and verification. |
| Document Version Hygiene | Removes unaccepted S3 versions while preserving the accepted version. |

The lifecycle workers use conditional DynamoDB operations, bounded processing, pagination validation, scoped IAM permissions and failure handling.

The document version hygiene worker fails closed when the number of versions exceeds its configured processing threshold.

## 6. Infrastructure as Code

Terraform configuration is maintained in:

`terraform/environments/dev/`

The configuration covers:

- Networking and VPC endpoints.
- Security groups.
- API Gateway and ALB integration.
- Application compute.
- Cognito.
- DynamoDB.
- S3 storage and access logging.
- KMS encryption.
- Lambda functions and execution roles.
- EventBridge scheduling.
- CloudTrail.
- WAF.
- CloudWatch logging and alerts.

The Terraform configuration has passed local formatting and validation.

**Important:** Terraform configuration validation does not mean infrastructure has been deployed or tested against live AWS services.

## 7. CI/CD and Security Automation

Two GitHub Actions workflows are maintained.

### Continuous Integration

`.github/workflows/ci.yml`

Includes:

- Backend tests on Python 3.12 and 3.14.
- DynamoDB Local integration testing.
- Ruff linting and formatting checks.
- Python compilation checks.
- Frontend tests, TypeScript checks and production build.
- Terraform formatting and validation.
- TFLint.
- Container image build validation.
- Lambda packaging.

### Security Scanning

`.github/workflows/security.yml`

Includes:

- Gitleaks secret detection.
- Python dependency auditing with pip-audit.
- Frontend dependency auditing with npm audit.
- Terraform scanning with Checkov.
- Container vulnerability scanning with Trivy.

Third-party GitHub Actions are pinned to full commit SHAs.

Security scanning is designed to fail on configured high-severity findings with available fixes. Unfixed container findings are tracked separately rather than being represented as vulnerability-free results.

## 8. Testing and Local Verification

Latest recorded local verification:

| Component | Result |
|---|---:|
| Backend tests | 969 passed |
| Backend subtests | 8 passed |
| Frontend tests | 203 passed |
| TypeScript | Passed |
| ESLint | Passed |
| Frontend production build | Passed |
| Terraform formatting | Passed |
| Terraform validation | Passed |
| Checkov | 640 passed, 0 failed, 67 reviewed skips |
| Gitleaks | No leaks found |
| GitHub Actions actionlint | Passed |
| Lambda packaging tests | Passed |
| Docker build and health check | Passed |

These are local verification results. GitHub-hosted workflow execution and live AWS integration testing remain pending.

## 9. Container Security

The backend container uses:

- A Python 3.14 slim base image.
- A dedicated non-root user.
- Reduced Linux capabilities through a non-root runtime.
- Removed setuid permissions from mount utilities.
- Minimal application dependencies.
- No pip in the final runtime image.
- A Docker health check.

Trivy identified unfixed HIGH-severity vulnerabilities in some Debian base-image packages. These findings are documented in:

`docs/security/container-vulnerability-risk-assessment.md`

The project does not claim that the container is vulnerability-free.

## 10. Repository Structure

```text
.
├── .github/workflows/       # CI and security workflows
├── app/                     # FastAPI backend
├── docs/
│   ├── architecture/        # Architecture documentation
│   ├── security/            # Security assessments and controls
│   └── threat-model/         # Threat modelling
├── evidence/
│   └── container-security/  # Trivy reports and experiments
├── frontend/                # React and TypeScript application
├── lambda/                  # Serverless lifecycle functions
├── scripts/                 # Packaging and bootstrap utilities
├── terraform/
│   └── environments/dev/    # AWS infrastructure
├── tests/                   # Unit and integration tests
├── Dockerfile
├── requirements.txt
└── requirements-dev.txt
```