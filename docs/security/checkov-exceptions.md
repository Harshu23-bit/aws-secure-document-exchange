# Checkov Findings and Accepted Exceptions

**Project:** AWS Secure Infrastructure Blueprint  
**Document:** Checkov Findings and Accepted Exceptions  
**Version:** 2.1  
**Review date:** 20 November 2026  
**Status:** Exception register maintained; latest local Checkov scan reports 640 passed, 0 failed and 67 skipped.

## Purpose

This document records Checkov findings that remain intentionally unresolved in the AWS Secure Infrastructure Blueprint.

Findings are not globally suppressed. They remain visible in security scans so their rationale and residual risks can be reviewed.

These decisions apply to this temporary demonstration environment. They are not blanket approvals for production deployments.

## 1. KMS key policy findings

Affected checks:
- CKV_AWS_356
- CKV_AWS_109
- CKV_AWS_111

Affected policy documents:
- `aws_iam_policy_document.application_kms`
- `aws_iam_policy_document.waf_logs`
- `aws_iam_policy_document.cloudtrail_kms`

Rationale:

The KMS key policies include an account-root principal statement with `kms:*`. This follows the standard AWS KMS account-level delegation model, allowing IAM policies in the account to delegate access to the key.

The `Resource = "*"` in a KMS key policy applies to the key associated with that policy. It does not independently grant every IAM identity access.

The service-principal statements are separately scoped to their intended services and, where applicable, their encryption contexts.

Decision:

Retain these statements. Review effective IAM permissions and key access before production use.

## 2. ALB Security Group Ingress Exception

Affected check:
- CKV_AWS_260

Affected resource:
- `aws_vpc_security_group_ingress_rule.alb_from_vpc_link`

Rationale:

The internal Application Load Balancer accepts inbound TCP port 80 traffic exclusively from the API Gateway VPC Link security group.

The Checkov policy does not correctly recognize the `referenced_security_group_id` attribute used by this standalone security group ingress rule.

The rule does not permit public CIDR-based ingress.

The network path is restricted through security-group references:

- API Gateway VPC Link security group → internal ALB, TCP 80.
- Internal ALB security group → application security group, TCP 8080.
- Application security group accepts traffic only from the ALB security group.

Decision:

Retain the security-group-referenced ingress rule. Do not broaden ingress to public CIDR ranges to satisfy the scanner.

## 3. S3 encryption findings

Affected check:
- CKV_AWS_145

Affected resources:
- `aws_s3_bucket.vpc_flow_logs`
- `aws_s3_bucket.s3_access_logs`

### VPC Flow Logs bucket

Encryption:
- SSE-S3 (`AES256`)

Rationale:

The VPC Flow Logs bucket uses SSE-S3 for encryption at rest.

AWS supports SSE-S3 and SSE-KMS for VPC Flow Logs delivered to S3. A customer-managed KMS key would introduce additional key-policy configuration, service permissions and recurring KMS costs.

The current demonstration environment does not require customer-managed encryption keys for network flow logs.

### S3 server access logs destination bucket

Encryption:
- SSE-S3 (`AES256`)

Rationale:

The S3 server access logging destination bucket uses SSE-S3.

AWS requires the destination bucket to use SSE-S3 default encryption for S3 server access logging. SSE-KMS default encryption is not supported for this destination.

Using SSE-KMS here could prevent successful delivery of server access logs.

### Encryption architecture

The application data bucket and CloudTrail bucket separately use SSE-KMS with customer-managed KMS keys.

This provides differentiated encryption controls according to the storage purpose and service compatibility requirements.

Decision:

Retain SSE-S3 for both logging buckets.

Do not change their encryption configuration solely to satisfy CKV_AWS_145.

Reassess encryption requirements, key-management boundaries and service compatibility before production deployment.

### CKV_AWS_144 — S3 cross-region replication

**Affected resources:**
- `aws_s3_bucket.application`
- `aws_s3_bucket.cloudtrail`
- `aws_s3_bucket.vpc_flow_logs`
- `aws_s3_bucket.s3_access_logs`

**Decision:** Accepted exception.

The project intentionally uses a single-region architecture in `ap-south-1`. Cross-region replication is not configured for the four S3 buckets.

The application infrastructure, DynamoDB tables, KMS keys and networking are also deployed within the same region. Replicating S3 objects independently would not provide complete disaster recovery for the application.

Enabling cross-region replication would introduce additional destination storage, replication requests, inter-region data transfer costs, IAM permissions and, for SSE-KMS encrypted objects, additional KMS configuration and permissions.

The additional complexity and cost are not justified by the current development environment's availability and disaster-recovery requirements.

**Compensating controls:**
- S3 versioning is enabled on all four buckets.
- All buckets enforce private access through S3 Block Public Access.
- Server-side encryption is configured for all buckets.
- Lifecycle policies manage object retention and incomplete multipart uploads.
- CloudTrail provides centralized AWS API activity auditing.
- Dedicated buckets separate application documents, CloudTrail records, VPC Flow Logs and access logs.

**Limitations:**
- The architecture does not provide cross-region S3 disaster recovery.
- A regional outage can make the affected S3 data unavailable until the region recovers.
- Versioning does not provide independent protection against all account-level or privileged deletion scenarios.
- Replication into a separate account and region has not been implemented.

**Reconsider when:** Business continuity requirements, regional disaster-recovery objectives, regulatory obligations, or independent audit-log preservation requirements justify a multi-region or cross-account storage architecture.

## 5. S3 event notifications

Affected check:
- CKV2_AWS_62

Affected resources:
- Application S3 bucket
- VPC Flow Logs bucket
- S3 access logs bucket
- CloudTrail bucket
- Identity metadata bucket (`aws_s3_bucket.identity_metadata`)

Rationale:

The current project does not require event-driven S3 processing.

No Lambda, SQS, or SNS workflow depends on S3 object-created notifications.

The CloudTrail SNS topic is used for CloudTrail log-delivery notifications; it does not require S3 event notifications.

Decision:

Do not add unused event notifications solely to satisfy the scanner. Reassess if an event-driven workflow is introduced.

## 6. WAF managed-rule coverage

Affected check:
- CKV2_AWS_76

Affected resource:
- `aws_lb.application`

Policy implementation reviewed:
- Checkov 3.4.3
- `ALBWebACLConfiguredWIthLog4jVulnerability.json`

The ALB is associated with a regional WAFv2 Web ACL.

The Web ACL includes:
- `AWSManagedRulesKnownBadInputsRuleSet`
- `AWSManagedRulesAnonymousIpList`
- `AWSManagedRulesCommonRuleSet`
- A custom API rate-based rule scoped to `/api/v1/`

The installed Checkov policy requires:
- `AWSManagedRulesKnownBadInputsRuleSet`
- `AWSManagedRulesAnonymousIpList`

Despite its Log4j-related description, CKV2_AWS_76 checks for the presence of these managed rule groups. It does not independently verify comprehensive Log4j protection.

The Anonymous IP List managed rule group can block traffic originating from known anonymizing services, including certain VPNs, proxies and hosting providers.

This can affect legitimate users accessing the application through those networks.

Decision:

Retain the current managed-rule configuration for the development environment.

Before production deployment:
- Test legitimate access through expected VPN and proxy paths.
- Review managed-rule metrics and sampled requests.
- Evaluate false positives and consider rule exclusions where justified.
- Validate protection against the application's actual threat model.

Checkov currently passes CKV2_AWS_76. This confirms the policy's required rule-group presence, not comprehensive WAF effectiveness.

## 7. Review requirements

Before production use:

- Review KMS key policies and effective IAM permissions.
- Evaluate backend encryption between the ALB and EC2.
- Evaluate cross-region backup and replication requirements.
- Assess S3 event-driven monitoring requirements.
- Evaluate WAF managed-rule coverage and false-positive impact.
- Review all accepted findings against the production threat model.
- Consider a separate security/log archive account and cross-account log isolation.

## 8. Scope and limitations

These are documented risk decisions for a temporary portfolio demonstration.

They do not establish that the configuration is production-ready.

Checkov findings must remain visible during future scans. Any change to an accepted exception must be supported by an updated security review.

---

## DynamoDB Security Decisions

### CKV_AWS_119 — Customer-managed KMS encryption

**Affected resources:**
- `aws_dynamodb_table.submissions`
- `aws_dynamodb_table.tenant_memberships`
- `aws_dynamodb_table.audit_events`

**Decision:** Accepted exception.

DynamoDB encryption at rest is enabled by default using an AWS-owned encryption key.

Customer-managed KMS keys are not configured for these tables in the initial development environment. Customer-managed key control is implemented separately for application document storage in S3, where it provides an important security boundary.

Introducing a dedicated customer-managed KMS key for DynamoDB would add key-management responsibilities, KMS costs, and operational dependencies without a current requirement that justifies the additional complexity.

This decision has the following limitations:
- The project cannot independently manage the encryption key's lifecycle, key policy, rotation, or disablement.
- Customer-visible auditing of DynamoDB encryption key usage through the project's KMS CloudTrail events is not available for AWS-owned keys.
- The project does not have the same level of encryption-key control as it does for S3 document storage.

**Compensating controls:**
- IAM permissions restrict application access to specific DynamoDB tables and indexes.
- Tenant membership records are read-only to the application EC2 role.
- Point-in-time recovery is enabled on all three tables.
- Application authorization enforces tenant isolation and object-level access.
- DynamoDB encryption at rest remains enabled; this exception concerns customer-managed key control, not encryption being disabled.

**Reconsider when:** Regulatory requirements, contractual obligations, customer-managed key control, independent key lifecycle management, or auditable key-usage requirements justify introducing a dedicated DynamoDB customer-managed KMS key.

---

## JWKS Metadata Bucket — Additional Findings

### CKV_AWS_145 — Customer-managed KMS encryption

Affected resource:
- `aws_s3_bucket.identity_metadata`

Decision: Accepted exception.

The bucket stores public Cognito JWKS metadata. These public signing keys are not confidential credentials or private key material.

SSE-S3 provides encryption at rest without introducing an additional KMS dependency.

The integrity and availability of the JWKS document are more important than confidentiality of its public contents.

Controls:
- S3 Block Public Access enabled.
- BucketOwnerEnforced ownership controls.
- Versioning enabled.
- TLS-only bucket policy.
- EC2 read permission restricted to the exact JWKS object.
- Lambda write permission restricted to the exact JWKS object.

Retain SSE-S3.

### CKV_AWS_144 — Cross-region replication

Affected resource:
- `aws_s3_bucket.identity_metadata`

Decision: Accepted exception.

The metadata bucket follows the project's single-region development architecture.

The JWKS document can be regenerated by the synchronization Lambda from Cognito's public JWKS endpoint.

Versioning provides recovery from some accidental object updates, but does not provide regional disaster recovery.

Reassess independent regional recovery requirements before production deployment.

### CKV2_AWS_62 — S3 event notifications

Affected resource:
- `aws_s3_bucket.identity_metadata`

Decision: Accepted exception.

The JWKS synchronization process is initiated by EventBridge Scheduler. It does not depend on S3 object-created notifications.

Adding notifications would not improve the current synchronization design.

---

## JWKS Lambda Security Findings

### CKV_AWS_158 — CloudWatch Logs KMS encryption

Affected resource:
- `aws_cloudwatch_log_group.jwks_sync`

Decision: Accepted development exception.

The JWKS Lambda log group uses CloudWatch Logs encryption at rest with AWS-managed service encryption rather than a dedicated customer-managed KMS key.

The function logs operational synchronization information. It does not intentionally log JWTs, private signing keys, passwords or other application secrets.

A dedicated CMK would add key-policy configuration and operational dependencies for this low-sensitivity operational log group.

Reassess customer-managed encryption requirements before production deployment.

### CKV_AWS_338 — Log retention below one year

Affected resource:
- `aws_cloudwatch_log_group.jwks_sync`

Configured retention:
- 30 days.

Decision: Accepted development exception.

The JWKS Lambda log group contains operational execution logs rather than the authoritative application audit trail.

A 30-day retention period is sufficient for initial development troubleshooting while limiting log storage costs.

This does not replace the project's longer-term CloudTrail and application audit-event retention strategy.

Reassess retention against production incident investigation and compliance requirements.

### CKV_AWS_116 — Lambda Dead Letter Queue

Affected resource:
- `aws_lambda_function.jwks_sync`

Decision: Retain the configured asynchronous failure destination.

The Lambda asynchronous invocation configuration specifies an SQS failure destination through `aws_lambda_function_event_invoke_config.jwks_sync`.

The configuration also defines bounded asynchronous retries and event-age limits.

Checkov continues to report CKV_AWS_116 because its DLQ check does not necessarily recognize Lambda asynchronous failure destinations as equivalent to the function-level dead-letter configuration.

The configured SQS destination captures failed asynchronous invocation records and provides a mechanism for later investigation.

Do not add a duplicate failure mechanism solely to clear the finding. Verify actual failure delivery in AWS after deployment.

### CKV_AWS_117 — Lambda VPC attachment

Affected resource:
- `aws_lambda_function.jwks_sync`

Decision: Accepted architectural exception.

The synchronization Lambda intentionally runs outside the VPC.

It retrieves the public Cognito JWKS document over HTTPS. Keeping it outside the VPC avoids requiring NAT Gateway or another outbound internet connectivity mechanism.

The Lambda does not need private access to application resources other than its narrowly scoped S3 permissions.

Its execution role restricts S3 access to the designated JWKS object and limits other AWS permissions to logging, metrics and failure delivery.

Do not attach this Lambda to the VPC without first designing and validating an alternative outbound connectivity architecture.

### CKV_AWS_173 — Lambda environment variable encryption

Affected resource:
- `aws_lambda_function.jwks_sync`

Decision: Accepted exception.

The configured environment variables contain resource identifiers and configuration values:
- Cognito User Pool ID.
- JWKS metadata bucket name.
- CloudWatch metric namespace.

No passwords, access keys, tokens or other application secrets are stored in these variables.

The environment variables do not contain confidential authentication material requiring an additional customer-managed encryption key.

Reassess if secrets are introduced in future versions.

### CKV_AWS_50 — X-Ray tracing

Affected resource:
- `aws_lambda_function.jwks_sync`

Decision: Deferred.

Active X-Ray tracing is not currently required for the small scheduled synchronization function.

CloudWatch logs, Lambda execution metrics and failure alarms provide the initial operational visibility required by this development environment.

Reassess distributed tracing if the synchronization workflow becomes more complex or production observability requirements justify it.

### CKV_AWS_272 — Lambda code signing

Affected resource:
- `aws_lambda_function.jwks_sync`

Decision: Deferred to controlled artifact release and deployment.

The project has implemented GitHub Actions CI workflows and Lambda packaging. However, the existence of CI packaging and Lambda code-signing infrastructure does not establish that the complete release process builds, signs, publishes and deploys trusted artifacts through an enforced pipeline.

The current project validation does not include an automated AWS deployment workflow or verified end-to-end artifact-signing enforcement.

Before production deployment:
- Integrate artifact signing into the controlled release process.
- Restrict accepted signing profiles and publishers.
- Verify that Lambda code-signing enforcement is enabled for the deployed function.
- Validate the complete build-to-deployment artifact chain.
- Retain signing and deployment evidence.

### CKV_AWS_297 — EventBridge Scheduler encryption

Affected resource:
- `aws_scheduler_schedule.jwks_sync`

Decision: Accepted development exception.

The schedule target input contains an empty JSON object and does not carry credentials, tokens or confidential application data.

The schedule does not currently require a dedicated customer-managed KMS key for payload confidentiality.

Reassess if sensitive schedule input or production-specific encryption requirements are introduced.

## API Gateway, ALB and S3 Lifecycle Exceptions

### CKV2_AWS_20 — ALB HTTPS redirection

Affected resource:
- `aws_lb.application`

Decision: Accepted architectural exception.

The application load balancer is internal and deployed in private subnets. It accepts traffic only from the API Gateway VPC Link security group.

Public HTTPS terminates at Regional API Gateway. The internal ALB currently has an HTTP listener and does not implement HTTP-to-HTTPS redirection.

Adding an HTTPS listener requires a trusted internal certificate and a defined backend TLS architecture.

Reconsider when internal TLS and certificate lifecycle management are implemented.

### CKV2_AWS_51 — API Gateway client certificate

Affected resource:
- `aws_api_gateway_stage.application`

Decision: Deferred.

This Checkov policy requires an API Gateway client certificate for authentication to the backend. It does not check browser-to-API mutual TLS.

The current VPC Link integration uses HTTP to an internal ALB. Cognito authorizes API callers through the API Gateway Cognito authorizer.

Reconsider when HTTPS backend integration and certificate-based service authentication are implemented.

### CKV2_AWS_53 — API Gateway request validation

Affected resources:
- `aws_api_gateway_method.proxy`
- `aws_api_gateway_method.root`
- `aws_api_gateway_method.proxy_options`
- `aws_api_gateway_method.root_options`

Decision: Accepted architectural exception for methods without applicable request parameters.

The proxy method uses an API Gateway request validator to validate request parameters.

The root method has no path parameters requiring API Gateway validation. FastAPI and Pydantic perform application-level input validation.

The OPTIONS methods use MOCK integrations for CORS preflight and do not forward requests to the backend.

These exceptions do not replace application-level request validation.

### CKV_AWS_103 — ALB TLS policy

Affected resource:
- `aws_lb_listener.http`

Decision: Not applicable to the current listener configuration.

The internal ALB currently has no HTTPS listener. Its listener uses HTTP on port 80.

A TLS security policy becomes applicable when an HTTPS listener is introduced with a trusted internal certificate.

Reassess when internal HTTPS is implemented.

### CKV_AWS_120 — API Gateway response caching

Affected resource:
- `aws_api_gateway_stage.application`

Decision: Accepted architectural exception.

API Gateway response caching is intentionally disabled for the authenticated multi-tenant document API.

Tenant-scoped authorization, document permissions, frequently changing membership records and document states make shared response caching an unnecessary data-isolation and staleness risk.

Disabling caching also avoids additional API Gateway cache charges.

Retain the current configuration unless a future caching design can demonstrate safe tenant isolation and authorization-aware cache behavior.

### CKV_AWS_225 — API Gateway method caching

Affected resource:
- `aws_api_gateway_method_settings.application`

Decision: Accepted architectural exception.

Method-level caching is intentionally disabled.

Authorization and document-access decisions must be evaluated against current application state. Cached responses could otherwise become stale or incorrectly scoped.

Retain the current configuration.

### CKV_AWS_237 — API Gateway replacement lifecycle

Affected resource:
- `aws_api_gateway_rest_api.application`

Decision: Accepted architectural exception.

The REST API currently has no custom domain or API mapping.

Replacing the REST API changes its execute-api endpoint. Enabling `create_before_destroy` alone cannot guarantee endpoint continuity.

Reconsider when a stable custom-domain deployment strategy is implemented.

### CKV_AWS_300 — S3 incomplete multipart upload lifecycle

Affected resource:
- `aws_s3_bucket_lifecycle_configuration.lambda_signing_artifacts`

Decision: Existing lifecycle configuration satisfies the underlying requirement.

Both unsigned and signed Lambda artifact lifecycle rules explicitly abort incomplete multipart uploads after seven days.

The Checkov suppression records that the required cleanup configuration is already present. No additional lifecycle rule is necessary solely to satisfy the scanner.

Retain the existing lifecycle configuration and verify its behavior after deployment.

### CKV_AWS_378 — ALB target transport encryption

Affected resource:
- `aws_lb_target_group.application`

Decision: Accepted architectural exception for the temporary development environment.

Traffic from the internal ALB to application instances uses HTTP on TCP port 8080 within private subnets.

The application security group accepts this traffic only from the ALB security group. Application instances have no public ingress.

Security-group restrictions limit network reachability but do not encrypt the traffic.

Internal transport encryption remains a residual risk.

Reconsider HTTPS between the ALB and application targets before production deployment, including certificate provisioning, trust and renewal.

### CKV_AWS_73 — API Gateway X-Ray tracing

Affected resource:
- `aws_api_gateway_stage.application`

Decision: Deferred.

API Gateway X-Ray tracing is disabled because the FastAPI application does not currently have distributed tracing instrumentation.

Current observability includes:
- API Gateway access logs.
- API Gateway integration latency metrics.
- CloudWatch alarms.
- CloudTrail.
- AWS WAF logs.

Reconsider when application-level distributed tracing instrumentation and end-to-end trace propagation are implemented.

---

## Trivy Configuration Scan — Accepted Findings

### Scan details

Scanner: Trivy 0.76.2

Command:

`trivy config --tf-vars terraform/environments/dev/terraform.tfvars --format table terraform/environments/dev`

Scan scope:
- Terraform configuration in `terraform/environments/dev`.
- 9 configuration files detected.
- Terraform variable values supplied through `terraform.tfvars`.

Result:
- 9 findings.
- 1 HIGH public load balancer finding.
- 5 LOW Lambda tracing findings.
- 3 HIGH S3 encryption findings.

The variable-resolution warning observed during the initial scan was resolved by explicitly supplying the Terraform variable file.

These findings remain documented as historical scan evidence and architectural review decisions. They are not necessarily findings in the current Terraform configuration.

The recorded nine-finding result must not be presented as the latest Trivy configuration scan. A fresh scan is required to establish the current finding count and status.

These decisions are not globally suppressed scanner checks.

### 1. AWS-0053 — Public Application Load Balancer

Status: Superseded by the current network architecture.

The earlier Trivy finding described an internet-facing Application Load Balancer with `internal = false`.

The current Terraform configuration uses:

- `internal = true`.
- Private subnets in two Availability Zones.
- Inbound TCP port 80 restricted to the API Gateway VPC Link security group.
- No public ALB ingress.
- Public HTTPS termination at Regional API Gateway.

The earlier public ALB finding must not be treated as a current accepted exposure without confirmation from a fresh Trivy scan.

The current architecture still has an internal transport-encryption limitation: VPC Link-to-ALB and ALB-to-application traffic use HTTP.

Verify the current configuration through subsequent Trivy scans and deployment testing.

### 2. AWS-0066 — Lambda Active Tracing Disabled

Severity: LOW

Affected resources:
- `aws_lambda_function.document_cleanup`
- `aws_lambda_function.document_expiry`
- `aws_lambda_function.document_finalization`
- `aws_lambda_function.document_version_hygiene`
- `aws_lambda_function.jwks_sync`

Finding:

The five Lambda functions do not have active AWS X-Ray tracing enabled.

Decision: Accepted development exception.

Active tracing is deferred to control development-environment costs and operational complexity.

The current scheduled Lambda workflows have CloudWatch logging, execution metrics, alarms and asynchronous failure destinations where applicable.

These provide the initial operational visibility required by the development environment.

Limitations:
- Distributed traces are unavailable.
- End-to-end request and service dependency analysis is limited.
- Diagnosing complex latency and cross-service execution problems may require additional investigation through logs and metrics.

Reconsider when:

The application moves toward production, workflows become more complex, or incident investigation and performance monitoring requirements justify distributed tracing.

### 3. AWS-0132 — S3 Customer-Managed KMS Encryption

Severity: HIGH

Affected resources:
- `aws_s3_bucket.identity_metadata`
- `aws_s3_bucket.lambda_signing_artifacts`
- `aws_s3_bucket.vpc_flow_logs`

Finding:

The three buckets use SSE-S3 (`AES256`) rather than SSE-KMS with a customer-managed KMS key.

Decision: Accepted encryption-design exception.

#### Identity metadata bucket

Resource:
- `aws_s3_bucket.identity_metadata`

The bucket stores public Cognito JWKS metadata.

The signing keys contained in the JWKS document are public verification keys, not private signing keys or confidential credentials.

SSE-S3 provides encryption at rest without introducing another KMS dependency for this metadata.

Additional controls:
- S3 Block Public Access.
- Bucket ownership enforced through BucketOwnerEnforced.
- Versioning enabled.
- TLS-only bucket access.
- EC2 read access restricted to the required JWKS object.
- Lambda write access restricted to the required JWKS object.

The confidentiality benefit of a dedicated customer-managed key is limited for this particular public metadata.

Retain SSE-S3.

#### Lambda signing artifacts bucket

Resource:
- `aws_s3_bucket.lambda_signing_artifacts`

The bucket stores private Lambda deployment and code-signing artifacts.

SSE-S3 provides encryption at rest for these artifacts.

The current development workflow does not require an additional customer-managed KMS key for this temporary artifact storage.

This decision does not imply that the artifacts are public or that their integrity is unimportant.

Artifact integrity is addressed separately through the Lambda code-signing workflow and deployment controls.

Reconsider customer-managed encryption if production artifact-protection requirements, regulatory obligations or key-management policies justify it.

#### VPC Flow Logs bucket

Resource:
- `aws_s3_bucket.vpc_flow_logs`

The bucket stores network flow-log records and uses SSE-S3.

The development architecture does not currently require customer-managed encryption keys for this logging destination.

Introducing a dedicated KMS key would add key-policy configuration, service permissions and recurring KMS costs.

The logs remain protected through private bucket access, encryption at rest and the configured storage lifecycle controls.

Reassess the encryption choice if production security classification, compliance or independent key-management requirements demand customer-managed encryption.

#### Overall decision

Retain SSE-S3 for all three buckets.

Do not change their encryption configuration solely to satisfy AWS-0132.

The application's sensitive document storage and CloudTrail storage separately use SSE-KMS with customer-managed keys. Encryption decisions are differentiated according to storage purpose and security requirements.

### 4. Review requirements

Before production deployment:

- Reassess the public API Gateway ingress and edge-protection architecture.
- Evaluate internal transport encryption between API Gateway, ALB and application targets.
- Review internal certificate provisioning, trust and renewal requirements.
- Reassess X-Ray tracing and distributed observability requirements.
- Review the sensitivity classification of each S3 bucket.
- Reassess customer-managed KMS requirements for signing artifacts and network logs.
- Verify that all documented compensating controls are actually enforced after deployment.
- Review Trivy findings again when Terraform configurations or scanner policies change.

### 5. Scope and limitations

These decisions apply to the temporary development and portfolio demonstration environment.

A HIGH severity scanner finding does not automatically establish an exploitable vulnerability. However, accepted findings still represent security trade-offs and must not be treated as universally safe configurations.

The decisions documented here do not establish production readiness.

All findings must remain visible during subsequent Trivy scans. Any change to an accepted exception must be supported by an updated security review.
