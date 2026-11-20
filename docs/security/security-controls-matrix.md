# Security Controls Matrix

**Project:** AWS Secure Infrastructure Blueprint  
**Document:** Security Controls Matrix  
**Version:** 1.0  
**Review date:** 20 November 2026  
**Status:** Local implementation and configuration review completed; AWS deployment and live validation pending.

---

## 1. Purpose

This document provides a consolidated mapping of the security controls implemented or configured for the AWS Secure Infrastructure Blueprint.

It connects each security objective to:

- The relevant security control.
- The component or layer responsible for enforcement.
- The implementation location.
- The available validation evidence.
- Any remaining limitations or deployment dependencies.

The matrix supports architecture review, security assessment, remediation tracking, and future deployment validation.

It is not a certification, penetration-test report, or proof that deployed AWS resources enforce the intended configuration.

## 2. Scope

This matrix covers the following security domains:

1. Identity and authentication.
2. Authorization and tenant isolation.
3. Application and API security.
4. Document upload and download security.
5. Data protection and cryptographic controls.
6. Network security.
7. Compute and container security.
8. Infrastructure as Code security.
9. Logging, monitoring, and auditability.
10. Scheduled workload and lifecycle security.
11. Frontend and browser security.
12. CI/CD and software supply-chain security.
13. Operational security and resilience.

The review considers application source code, Terraform configuration, Lambda implementations, automated tests, container configuration, and local validation results.

### 2.1 Control Status Definitions

| Status | Meaning |
|---|---|
| Implemented — locally validated | The control exists in application code or local configuration and has supporting local validation evidence. |
| Configured — deployment pending | The control is defined in Terraform or another deployment configuration, but has not been verified against deployed AWS resources. |
| Partially implemented | The control exists but has a known limitation or incomplete enforcement scope. |
| Pending validation | The intended control exists, but its actual behavior requires further testing or evidence. |
| Hardening recommended | The control is an improvement opportunity rather than a confirmed security defect. |
| Not implemented | The capability is not currently present in the reviewed project. |

A configured Terraform resource must not automatically be treated as a deployed or operational security control.

## 3. Identity and Authentication Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| IAM-01 | Protect AWS root access | Root MFA enabled; root access keys absent. | AWS account configuration | AWS account setup review | Configured — account setup completed |
| IAM-02 | Avoid routine root usage | Administrative project access uses IAM Identity Center and an assumed role. | AWS identity management | `aws sts get-caller-identity` using project profile | Configured — account setup completed |
| IAM-03 | Authenticate application users | Amazon Cognito User Pool with admin-created users. | Cognito | Terraform configuration review | Configured — deployment pending |
| IAM-04 | Prevent public-client secret exposure | Browser and native clients are public clients without client secrets. | Cognito application clients | Terraform configuration review | Configured — deployment pending |
| IAM-05 | Use secure browser authentication | Browser client uses OAuth Authorization Code flow. | Cognito and frontend | Amplify configuration and frontend source review | Implemented locally; AWS deployment pending |
| IAM-06 | Restrict API token type | Backend accepts access tokens rather than ID tokens. | FastAPI authentication | Authentication source review and tests | Implemented — locally validated |
| IAM-07 | Validate token signature | JWT verification uses RS256 and trusted Cognito JWKS keys. | Backend security module | Authentication and JWKS tests | Implemented — locally validated |
| IAM-08 | Validate token claims | Issuer, expiration, issued-at, subject, token use, client ID, and required scope are checked. | Backend security module | Authentication source review and tests | Implemented — locally validated |
| IAM-09 | Restrict API access scope | API requires `cloudsec-api/access`. | Cognito authorizer and FastAPI | Terraform and backend source review | Configured and implemented; deployment pending |
| IAM-10 | Limit token abuse through size constraints | JWT and key identifier size limits are enforced. | Backend security module | Authentication source review | Implemented — locally validated |
| IAM-11 | Protect authentication state | Frontend tracks loading, authenticated, unauthenticated, and error states. | React authentication provider | AuthProvider tests | Implemented — locally validated |
| IAM-12 | Prevent stale authentication refresh results | Refresh operation sequencing prevents stale asynchronous results from overwriting newer state. | React authentication provider | Refresh-race regression tests | Implemented — locally validated |
| IAM-13 | Handle invalid authorization scope | Invalid-scope refresh clears user state and cached query data. | React authentication provider | Regression test for invalid-scope refresh | Implemented — locally validated |
| IAM-14 | Protect JWKS synchronization | Scheduled JWKS synchronization validates HTTPS, rejects redirects, and validates retrieved key material. | JWKS Lambda | Handler source review and tests | Implemented — locally validated |
| IAM-15 | Protect signing-key synchronization artifacts | JWKS artifacts are stored in a private S3 bucket and published through the configured synchronization process. | Lambda and S3 | Lambda and Terraform review | Configured — deployment pending |

### 3.1 Authentication Limitations

- Cognito configuration has not been validated against a deployed User Pool.
- Browser token storage uses the installed Amplify browser storage behavior, which uses local storage by default.
- Browser-accessible tokens remain exposed to successful same-origin script execution.
- The native Cognito client is configured for SRP, but the backend's accepted API client is the browser client.
- No live JWKS synchronization execution has been performed against AWS.

## 4. Authorization and Tenant Isolation Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| AUTHZ-01 | Enforce tenant membership | Membership is loaded using a strongly consistent DynamoDB read. | Backend membership service | Membership source review and tests | Implemented — locally validated |
| AUTHZ-02 | Reject inactive memberships | Only ACTIVE membership records authorize access. | Backend authorization service | Membership tests | Implemented — locally validated |
| AUTHZ-03 | Enforce role boundaries | Application checks explicit Submitter, Reviewer, and Tenant Admin roles. | Backend authorization service | Authorization and endpoint tests | Implemented — locally validated |
| AUTHZ-04 | Prevent cross-tenant access | Submission queries and authorization checks are tenant-scoped. | Backend services and repositories | Tenant isolation tests | Implemented — locally validated |
| AUTHZ-05 | Prevent submitter access to another user's submission | Submitter ownership is checked against the authenticated user. | Submission and workflow services | Submission authorization tests | Implemented — locally validated |
| AUTHZ-06 | Prevent tenant administrators from accessing document contents by default | Document service authorization does not grant Tenant Admin automatic document access. | Document service | Document authorization source review and tests | Implemented — locally validated |
| AUTHZ-07 | Prevent unauthorized role changes | Membership management validates actor permissions and target membership state. | Tenant service and membership repository | Tenant management tests | Implemented — locally validated |
| AUTHZ-08 | Prevent reviewer authorization races | Reviewer membership is checked inside the DynamoDB transaction that performs the workflow transition. | Workflow service and DynamoDB transaction | Transaction authorization tests | Implemented — locally validated |
| AUTHZ-09 | Enforce workflow transitions | Explicit allowed transitions, ownership, role, and version conditions are checked. | Workflow service and repository | Workflow tests | Implemented — locally validated |
| AUTHZ-10 | Prevent stale updates | Conditional writes and version checks protect submission state transitions. | DynamoDB repository | Workflow and repository tests | Implemented — locally validated |
| AUTHZ-11 | Restrict audit modification | Application IAM permissions do not grant audit-table UpdateItem or DeleteItem. | IAM policy | Terraform IAM policy review | Configured — deployment pending |
| AUTHZ-12 | Avoid trusting frontend role checks | Backend authorization remains authoritative regardless of frontend route or UI state. | Backend API | Backend source review and authorization tests | Implemented — locally validated |
| AUTHZ-13 | Reduce cursor misuse | Pagination cursors are checked against tenant, user, role, and expected key structure. | Submission service | Source review and pagination tests | Implemented — locally validated |

### 4.1 Authorization Limitations

- Pagination cursors are unsigned. Their contents are validated and bound to the caller's authorization context, but cursor signing remains an optional hardening improvement.
- Frontend route protection and role-aware rendering are usability controls, not independent authorization boundaries.
- AWS transaction behavior has been tested locally, not against a deployed DynamoDB environment.

## 5. API and Application Security Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| API-01 | Authenticate API requests | API Gateway Cognito authorizer and independent FastAPI authentication. | API Gateway and backend | Terraform and backend source review | Configured and implemented; deployment pending |
| API-02 | Restrict public API exposure | Regional API Gateway is the public API entry point. | API Gateway | Terraform review | Configured — deployment pending |
| API-03 | Restrict backend network access | Internal ALB is reachable through the configured VPC Link security group. | VPC security groups | Terraform review | Configured — deployment pending |
| API-04 | Reject unauthorized backend traffic | Application security group accepts TCP 8080 only from the ALB security group. | VPC security groups | Terraform review | Configured — deployment pending |
| API-05 | Restrict API request destinations | Frontend API client validates the intended API target before attaching an access token. | Frontend API client | Source review and frontend tests | Implemented — locally validated |
| API-06 | Prevent accidental credential forwarding to S3 | Presigned S3 upload uses a separate request without the Cognito bearer-token interceptor. | Frontend upload client | Source review | Implemented — locally validated |
| API-07 | Limit request duration | Frontend API requests use a configured timeout. | Axios API client | Frontend source review | Implemented — locally validated |
| API-08 | Restrict cross-origin access | API Gateway and FastAPI CORS configuration define permitted origins, methods, and headers. | API Gateway and FastAPI | Terraform and application source review | Configured — deployment pending |
| API-09 | Limit abusive API traffic | AWS WAF includes a source-IP rate-based rule. | AWS WAF | Terraform review | Configured — deployment pending |
| API-10 | Reduce common web attack exposure | AWS managed rules include Known Bad Inputs, Anonymous IP, and Common Rule Set. | AWS WAF | Terraform review | Configured — deployment pending |
| API-11 | Avoid sensitive request logging | API access logging is configured without intentionally logging authorization headers, request bodies, or document contents. | API Gateway logging | Terraform review | Configured — deployment pending |
| API-12 | Prevent production documentation exposure | FastAPI `/docs` and `/redoc` are currently enabled; production restriction is recommended. | FastAPI application configuration | `main.py` source review | Hardening recommended |
| API-13 | Improve backend transport protection | VPC Link-to-ALB-to-application traffic currently uses HTTP internally. | Internal network path | Terraform listener and target-group review | Hardening recommended |
| API-14 | Improve API observability | API Gateway X-Ray tracing is currently disabled. | API Gateway | Terraform review | Not implemented |

### 5.1 API Security Limitations

- The WAF rate-limit rule aggregates by source IP, not authenticated user or tenant.
- Its URI scope-down begins with `/api/api/v1/`; effective coverage must be verified against the deployed API stage and forwarded path.
- Internal HTTP is a transport-encryption limitation, not evidence of public exposure.
- Production behavior for `/docs` and `/redoc` must be addressed before deployment.

## 6. Document Upload and Download Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| DOC-01 | Restrict supported file formats | PDF, JPEG, and PNG are accepted. | Backend storage service | Storage tests | Implemented — locally validated |
| DOC-02 | Limit upload size | Maximum document size is 10 MiB. | Backend and S3 presigned policy | Storage tests | Implemented — locally validated |
| DOC-03 | Prevent client-controlled object paths | Object keys are generated using tenant, submission, and document identifiers. | Document service | Source review and document tests | Implemented — locally validated |
| DOC-04 | Sanitize uploaded filenames | Filename path components and control characters are removed. | Document service | Source review and tests | Implemented — locally validated |
| DOC-05 | Restrict upload authorization | Only authorized Submitters can create uploads for their own eligible submissions. | Document service | Document service/API tests | Implemented — locally validated |
| DOC-06 | Restrict upload content type | Presigned POST policy requires an allowed content type. | S3 presigned POST policy | Storage tests | Implemented — locally validated |
| DOC-07 | Enforce encryption on upload | Presigned POST policy requires SSE-KMS and the configured application KMS key. | S3 presigned POST policy and bucket policy | Storage tests and Terraform review | Implemented/configured; AWS deployment pending |
| DOC-08 | Enforce upload size at storage boundary | Presigned POST policy constrains content length. | S3 presigned POST policy | Storage tests | Implemented — locally validated |
| DOC-09 | Verify uploaded object metadata | Completion flow checks size, type, encryption mode, and exact KMS key. | Document service and storage service | Document service/API tests | Implemented — locally validated |
| DOC-10 | Bind document metadata to an exact object version | Completion requires a non-null S3 VersionId and validates the exact version. | Document service and S3 | Document service/API tests | Implemented — locally validated |
| DOC-11 | Validate file signatures | Content validation checks expected PDF, JPEG, and PNG signatures. | Backend storage service | Storage tests | Implemented — locally validated |
| DOC-12 | Prevent unauthorized downloads | Download authorization checks tenant, ownership, role, status, and document identity. | Document service | Document service/API tests | Implemented — locally validated |
| DOC-13 | Restrict download workflow states | Reviewer downloads are allowed only for configured eligible submission states. | Document service | Document service tests | Implemented — locally validated |
| DOC-14 | Bind download to an exact version | Presigned download references the accepted S3 VersionId. | Document service | Document service tests | Implemented — locally validated |
| DOC-15 | Limit presigned URL lifetime | Upload and download URLs use short configured expirations. | Backend storage service | Source review and tests | Implemented — locally validated |
| DOC-16 | Preserve accepted document versions | Version hygiene excludes the accepted version from cleanup. | Version hygiene Lambda | Stage D tests | Implemented — locally validated |
| DOC-17 | Avoid premature document metadata removal | Finalization verifies the S3 object key is empty before removing metadata. | Finalization Lambda | Stage C tests | Implemented — locally validated |
| DOC-18 | Prevent cleanup of unrelated object keys | Lifecycle workers validate exact tenant-scoped object keys and filter S3 version listings. | Lifecycle Lambda workers | Stage B, C, and D tests | Implemented — locally validated |

### 6.1 Document Security Limitations

- File-signature validation does not provide structural document validation or malware scanning.
- PDF validation checks the expected header signature; it does not establish that the document is safe to render.
- Presigned URL replay can create additional object versions within the URL's validity period.
- Stage D removes unaccepted versions, but this is cleanup rather than prevention of replay.
- Documents exceeding the configured 5,000-version processing threshold fail closed and require operational attention.
- S3 operations have not been validated against a deployed application bucket.

## 7. Data Protection and Cryptographic Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| DATA-01 | Encrypt application documents at rest | Application S3 bucket uses default SSE-KMS encryption. | S3 and KMS | Terraform review | Configured — deployment pending |
| DATA-02 | Encrypt database data at rest | DynamoDB tables use the configured application KMS key. | DynamoDB and KMS | Terraform review | Configured — deployment pending |
| DATA-03 | Protect cryptographic key lifecycle | KMS key rotation is enabled for configured keys. | AWS KMS | Terraform review | Configured — deployment pending |
| DATA-04 | Restrict public object access | S3 Block Public Access is enabled at all four settings for application and logging buckets. | S3 | Terraform review | Configured — deployment pending |
| DATA-05 | Prevent insecure bucket transport | Bucket policies deny requests that do not use secure transport. | S3 bucket policies | Terraform review | Configured — deployment pending |
| DATA-06 | Enforce application bucket encryption | Bucket policy denies object uploads that do not use the required KMS encryption configuration. | S3 bucket policy | Terraform review | Configured — deployment pending |
| DATA-07 | Prevent ownership ambiguity | S3 Object Ownership uses BucketOwnerEnforced. | S3 | Terraform review | Configured — deployment pending |
| DATA-08 | Preserve object recovery capability | Application bucket versioning is enabled. | S3 | Terraform review | Configured — deployment pending |
| DATA-09 | Protect database recovery | DynamoDB point-in-time recovery is enabled. | DynamoDB | Terraform review | Configured — deployment pending |
| DATA-10 | Reduce abandoned multipart storage | Incomplete multipart uploads are configured for lifecycle abortion. | S3 lifecycle | Terraform review | Configured — deployment pending |
| DATA-11 | Limit application data access | IAM policies scope DynamoDB and S3 access to required resources and actions. | IAM | Terraform policy review | Configured — deployment pending |
| DATA-12 | Preserve audit records | Audit table IAM permissions omit UpdateItem and DeleteItem. | IAM and DynamoDB | Terraform policy review | Configured — deployment pending |
| DATA-13 | Reduce stored object versions | Lifecycle policies and Stage D cleanup remove eligible old versions. | S3 lifecycle and Lambda | Terraform review and Stage D tests | Configured/implemented; deployment pending |

### 7.1 Cryptographic Limitations

- KMS key policies and service integrations have not been exercised against deployed AWS resources.
- Key rotation configuration does not demonstrate successful rotation operations.
- S3 server-side encryption does not replace transport encryption between every internal application component.
- Application-level encryption beyond the configured AWS storage encryption controls is not claimed.

## 8. Network Security Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| NET-01 | Isolate application resources | VPC with public and private subnets across two Availability Zones. | Amazon VPC | Terraform review | Configured — deployment pending |
| NET-02 | Keep application compute private | EC2 instances are placed in private subnets without public IP assignment. | EC2 and VPC | Terraform review | Configured — deployment pending |
| NET-03 | Avoid direct public ALB access | ALB is internal and accepts traffic only from the VPC Link security group. | ALB and security groups | Terraform review | Configured — deployment pending |
| NET-04 | Restrict VPC Link traffic | VPC Link security group egress is limited to the ALB listener port. | Security groups | Terraform review | Configured — deployment pending |
| NET-05 | Restrict ALB-to-application traffic | ALB egress is limited to application TCP 8080. | Security groups | Terraform review | Configured — deployment pending |
| NET-06 | Restrict application ingress | Application security group accepts TCP 8080 only from the ALB security group. | Security groups | Terraform review | Configured — deployment pending |
| NET-07 | Remove default security-group access | Default security group has empty ingress and egress rules. | VPC security group | Terraform review | Configured — deployment pending |
| NET-08 | Monitor network traffic | VPC Flow Logs capture ALL traffic and deliver to S3. | VPC Flow Logs | Terraform review | Configured — deployment pending |
| NET-09 | Provide private AWS service connectivity | S3 and DynamoDB gateway endpoints and selected interface endpoints are configured. | VPC endpoints | Terraform review | Configured — deployment pending |
| NET-10 | Reduce dependency on internet egress | No NAT Gateway is configured. | VPC routing | Terraform review | Configured; operational validation pending |
| NET-11 | Preserve network audit evidence | Flow Log bucket uses private access, encryption, lifecycle rules, and access logging. | S3 | Terraform review | Configured — deployment pending |

### 8.1 Network Limitations

- Interface endpoints are currently configured in only one private subnet. This is a resilience limitation.
- The private route table has no default internet route.
- EC2 bootstrap installs Docker using package repositories. Package access must be validated in the deployed environment because no NAT Gateway is configured.
- Internal HTTP between VPC Link, ALB, and application targets remains a transport-encryption hardening opportunity.
- Flow Log delivery has not been verified in AWS.

## 9. Compute and Container Security Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| CMP-01 | Use private compute | EC2 Auto Scaling instances are configured for private subnets. | EC2 and ASG | Terraform review | Configured — deployment pending |
| CMP-02 | Require IMDSv2 | Instance metadata service requires tokens. | EC2 instance metadata | Terraform review | Configured — deployment pending |
| CMP-03 | Reduce metadata exposure | Metadata response hop limit is set to one. | EC2 instance metadata | Terraform review | Configured — deployment pending |
| CMP-04 | Encrypt instance storage | Root EBS volume uses encryption. | EBS | Terraform review | Configured — deployment pending |
| CMP-05 | Restrict administrative access | SSM instance role and private service endpoints are configured. | IAM, SSM, and VPC | Terraform review | Configured — deployment pending |
| CMP-06 | Avoid privileged application execution | Container runs under UID/GID 10001. | Docker runtime | Local container inspection | Implemented — locally validated |
| CMP-07 | Reduce container filesystem modification | Container uses a read-only root filesystem. | Docker runtime | Local container inspection | Implemented — locally validated |
| CMP-08 | Reduce Linux capabilities | Container drops all capabilities. | Docker runtime | Local container inspection | Implemented — locally validated |
| CMP-09 | Prevent privilege escalation | `no-new-privileges` is enabled. | Docker runtime | Local container inspection | Implemented — locally validated |
| CMP-10 | Restrict container resources | Memory and PID limits are configured. | Docker runtime | Local container inspection | Implemented — locally validated |
| CMP-11 | Restrict temporary storage | `/tmp` uses bounded tmpfs with `noexec`, `nosuid`, and `nodev`. | Docker runtime | Docker configuration review | Implemented — locally validated |
| CMP-12 | Protect container image distribution | ECR repository uses immutable tags, image scanning on push, KMS encryption, and lifecycle rules. | Amazon ECR | Terraform review | Configured — deployment pending |
| CMP-13 | Restrict image retrieval | Application IAM permissions use scoped ECR pull actions. | IAM and ECR | Terraform review | Configured — deployment pending |
| CMP-14 | Restrict deployment to trusted Lambda artifacts | Lambda code-signing configuration enforces trusted signing profiles. | AWS Signer and Lambda | Terraform review | Configured — deployment pending |
| CMP-15 | Bound application logs | Container JSON log rotation is configured. | Docker logging | Docker configuration review | Implemented — locally validated |

### 9.1 Container Validation Evidence

Local runtime validation confirmed the application container used:

- Non-root UID 10001.
- Read-only root filesystem.
- Dropped Linux capabilities.
- `no-new-privileges`.
- 512 MiB memory limit.
- PID limit of 100.

The `/health` and `/api/v1/health` endpoints returned HTTP 200 during local validation.

The local validation does not prove the same runtime behavior on deployed EC2 instances.

## 10. Infrastructure as Code and Configuration Security

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| IaC-01 | Maintain reproducible infrastructure | AWS resources are defined using Terraform. | Terraform | `terraform fmt` and `terraform validate` | Implemented — locally validated |
| IaC-02 | Detect insecure infrastructure configuration | Checkov scans Terraform resources and policies. | Checkov | Latest recorded scan: 640 passed, 0 failed, 67 skipped | Implemented — locally validated |
| IaC-03 | Document accepted scanner exceptions | Checkov exceptions are documented in `docs/security/checkov-exceptions.md`. | Security documentation | Documentation review | Implemented |
| IaC-04 | Detect configuration drift before deployment | Terraform plan is available for reviewing intended changes. | Terraform workflow | Local Terraform validation | Pending deployment workflow validation |
| IaC-05 | Avoid committing sensitive configuration | `.gitignore` excludes credentials, environment files, and Terraform variable files. | Repository configuration | `.gitignore` review | Implemented — locally validated |
| IaC-06 | Validate Terraform formatting | Terraform formatting checks are run. | Terraform CLI | Formatting validation | Implemented — locally validated |
| IaC-07 | Validate Terraform syntax and references | Terraform validation is run. | Terraform CLI | Validation completed successfully | Implemented — locally validated |

### 10.1 Infrastructure Validation Limitations

- Terraform validation confirms configuration consistency, not successful AWS deployment.
- Checkov results reflect the scanned local configuration and its documented exceptions.
- The current Terraform state contains zero managed resources.
- No deployed-resource configuration or drift assessment has been performed.
- Terraform validation reported existing DynamoDB `hash_key` deprecation warnings.

## 11. Logging, Monitoring, and Audit Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| LOG-01 | Record AWS management activity | Multi-region CloudTrail trail records management read/write events and global service events. | AWS CloudTrail | Terraform review | Configured — deployment pending |
| LOG-02 | Protect CloudTrail integrity | Log-file validation is enabled. | CloudTrail | Terraform review | Configured — deployment pending |
| LOG-03 | Protect CloudTrail storage | Private S3 bucket, SSE-KMS, versioning, TLS enforcement, and lifecycle rules. | S3 and KMS | Terraform review | Configured — deployment pending |
| LOG-04 | Centralize CloudTrail events | CloudTrail is configured to deliver to a CloudWatch Logs group. | CloudTrail and CloudWatch | Terraform review | Configured — deployment pending |
| LOG-05 | Detect root account usage | Metric filter and alarm are configured. | CloudWatch Logs and Alarms | Terraform review | Configured — deployment pending |
| LOG-06 | Detect failed console sign-ins | Metric filter and alarm are configured. | CloudWatch Logs and Alarms | Terraform review | Configured — deployment pending |
| LOG-07 | Detect unauthorized API activity | Metric filter and alarm detect relevant access-denied events. | CloudWatch Logs and Alarms | Terraform review | Configured — deployment pending |
| LOG-08 | Detect IAM policy changes | Metric filter and alarm monitor relevant IAM changes. | CloudWatch Logs and Alarms | Terraform review | Configured — deployment pending |
| LOG-09 | Detect identity and credential changes | Metric filter and alarm monitor relevant IAM identity changes. | CloudWatch Logs and Alarms | Terraform review | Configured — deployment pending |
| LOG-10 | Detect security-group modifications | Metric filter and alarm monitor security-group changes. | CloudWatch Logs and Alarms | Terraform review | Configured — deployment pending |
| LOG-11 | Detect CloudTrail tampering | Metric filter and alarm monitor selected trail modification and deletion events. | CloudWatch Logs and Alarms | Terraform review | Configured — deployment pending |
| LOG-12 | Route security alerts | CloudWatch alarms publish to an encrypted SNS topic. | CloudWatch and SNS | Terraform review | Configured — deployment pending |
| LOG-13 | Record network traffic metadata | VPC Flow Logs deliver traffic metadata to S3. | VPC Flow Logs | Terraform review | Configured — deployment pending |
| LOG-14 | Preserve ALB request records | ALB access logging is configured to S3. | ALB and S3 | Terraform review | Configured — deployment pending |
| LOG-15 | Protect WAF visibility | WAF logging is configured to CloudWatch with Authorization-header redaction. | WAF and CloudWatch | Terraform review | Configured — deployment pending |
| LOG-16 | Monitor scheduled worker failures | Lambda error, queue, and stale-heartbeat alarms are configured for relevant workers. | Lambda and CloudWatch | Terraform review | Configured — deployment pending |
| LOG-17 | Preserve application audit events | Workflow transactions write audit events alongside state changes. | Backend and DynamoDB | Workflow and repository tests | Implemented — locally validated |
| LOG-18 | Restrict audit access | Tenant audit queries are tenant-scoped and role-restricted. | Backend audit service | Source review and frontend/backend tests | Implemented — locally validated |

### 11.1 Logging and Audit Limitations

- CloudTrail data event selectors for S3 object-level activity have not been configured in the reviewed trail.
- CloudTrail currently covers account-level management events, not organization-wide CloudTrail coverage.
- S3 server access logging is best-effort and must not be treated as real-time audit evidence.
- WAF configuration redacts the Authorization header; no broader redaction claim is made.
- SNS notification delivery, alarm evaluation, and operational response have not been tested in AWS.
- The CloudTrail SNS KMS permission scope remains a policy-hardening review item. It is not currently classified as a confirmed vulnerability.

## 12. Scheduled Workload and Lifecycle Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| JOB-01 | Synchronize trusted signing keys | JWKS sync Lambda retrieves and publishes validated key material. | Lambda | JWKS handler tests | Implemented — locally validated |
| JOB-02 | Expire abandoned pending uploads | Stage A validates expiry candidates and updates submission counters transactionally. | Document expiry Lambda | Stage A tests and source review | Implemented — locally validated |
| JOB-03 | Remove expired S3 versions | Stage B validates object identity and removes eligible versions and delete markers. | Document cleanup Lambda | Stage B tests and source review | Implemented — locally validated |
| JOB-04 | Finalize cleaned document records safely | Stage C verifies the exact S3 key is empty before metadata deletion. | Document finalization Lambda | Stage C focused tests | Implemented — locally validated |
| JOB-05 | Preserve accepted document versions | Stage D deletes unaccepted versions while preserving the accepted version. | Document version hygiene Lambda | Stage D unit and integration tests | Implemented — locally validated |
| JOB-06 | Prevent overlapping worker execution | Lifecycle workers use reserved concurrency of one where configured. | Lambda | Terraform review | Configured — deployment pending |
| JOB-07 | Bound worker execution | Worker timeout, memory, batch size, and remaining-time checks are configured. | Lambda | Terraform review and Stage D tests | Implemented/configured; deployment pending |
| JOB-08 | Retry transient asynchronous failures | Lambda asynchronous retry and maximum event-age settings are configured. | Lambda asynchronous invocation | Terraform review | Configured — deployment pending |
| JOB-09 | Preserve failed events | Failure destinations and dead-letter queues are configured for relevant workers. | Lambda and SQS | Terraform review | Configured — deployment pending |
| JOB-10 | Bound scheduled invocation retries | EventBridge Scheduler retry policies and DLQs are configured. | EventBridge Scheduler | Terraform review | Configured — deployment pending |
| JOB-11 | Avoid unsafe cleanup after incomplete processing | Conditional DynamoDB operations and verification checks protect cleanup finalization. | Lambda and DynamoDB | Stage B, C, and D tests | Implemented — locally validated |
| JOB-12 | Prevent stale candidate processing | Workers validate entity identity, status, timestamps, and expected index attributes. | Lambda handlers | Stage A–D tests | Implemented — locally validated |

### 12.1 Lifecycle Processing Limitations

- Stage A–D behavior has been tested locally; no scheduled worker has been executed against deployed AWS resources.
- Reserved concurrency of one currently prevents concurrent execution of the corresponding worker function.
- Increasing concurrency or introducing multiple consumers requires reassessment of cleanup coordination.
- Processing failures can leave eligible work pending for retry or operational investigation.
- The Stage D 5,000-version limit intentionally fails closed rather than attempting unbounded cleanup.

## 13. Frontend and Browser Security Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| FE-01 | Protect application routes | Protected routes check authentication state before rendering protected content. | React Router | Frontend tests | Implemented — locally validated |
| FE-02 | Enforce role-aware user experience | UI components expose actions according to the current role. | React components | Component tests and source review | Implemented — locally validated |
| FE-03 | Prevent stale user data exposure | Query cache is cleared when user identity changes or authentication ends. | TanStack Query and AuthProvider | Authentication tests | Implemented — locally validated |
| FE-04 | Isolate tenant query state | Query keys include relevant user and tenant context. | TanStack Query | Source review and tests | Implemented — locally validated |
| FE-05 | Restrict tenant selection | Tenant provider accepts authorized tenant identifiers. | Frontend tenant provider | Tenant provider tests | Implemented — locally validated |
| FE-06 | Avoid unsafe DOM rendering | Reviewed frontend source does not use the identified unsafe HTML injection sinks. | React application | Source search and review | Implemented — locally validated |
| FE-07 | Protect external document links | Download links opened in a new tab use `noopener noreferrer`. | Frontend document UI | Source review | Implemented — locally validated |
| FE-08 | Restrict direct upload requests | S3 upload requests do not attach the application bearer token. | Frontend upload flow | Source review | Implemented — locally validated |
| FE-09 | Limit client-side file selection | Client checks file type and size before requesting upload authorization. | Frontend upload component | Component tests | Implemented — locally validated |
| FE-10 | Protect production browser execution | CSP, HSTS, frame restrictions, and related security headers are required at the hosting layer. | Future frontend hosting layer | Hosting configuration not yet present | Pending implementation |
| FE-11 | Restrict production origins | Production frontend origin and Cognito callback URLs must be explicitly configured. | Frontend hosting and Cognito | Deployment configuration pending | Pending validation |
| FE-12 | Reduce browser token exposure | Current Amplify local-storage behavior is documented as a residual browser security risk. | Browser authentication storage | Frontend source and dependency review | Hardening recommended |

### 13.1 Frontend Limitations

- No production frontend hosting configuration currently exists in the reviewed Terraform or repository.
- No CloudFront, frontend S3 hosting, Amplify Hosting, or reverse-proxy deployment has been established.
- Production security headers have not been implemented at a hosting layer.
- Production CSP must be designed around the actual Cognito and API origins.
- HSTS should only be enabled after HTTPS is correctly configured.
- Client-side checks must never replace backend authorization or document validation.

## 14. CI/CD and Software Supply-Chain Controls

| ID | Security objective | Control and implementation | Enforcement layer | Validation evidence | Status |
|---|---|---|---|---|---|
| CICD-01 | Maintain automated validation capability | Repository includes GitHub Actions workflow structure. | GitHub Actions | Repository structure review | Partially implemented |
| CICD-02 | Validate Terraform changes | Terraform formatting and validation are available as local checks. | Terraform CLI | Local command results | Implemented locally; CI enforcement pending |
| CICD-03 | Scan infrastructure configuration | Checkov is configured for Terraform scanning. | Checkov | Recorded scan results | Implemented locally; CI enforcement pending |
| CICD-04 | Scan container images | Local Trivy tooling is available for container vulnerability assessment. | Trivy | Container security review | Local tooling available; CI enforcement pending |
| CICD-05 | Protect Lambda deployment artifacts | AWS Signer and Lambda code-signing enforcement are configured in Terraform. | AWS Signer and Lambda | Terraform review | Configured — deployment pending |
| CICD-06 | Protect container distribution | ECR image immutability and scan-on-push configuration are defined. | ECR | Terraform review | Configured — deployment pending |
| CICD-07 | Avoid publishing credentials | Repository ignore rules exclude sensitive local configuration files. | Git repository configuration | `.gitignore` review | Implemented locally |
| CICD-08 | Establish deployment approval controls | Production deployment approval and environment protection have not been validated. | GitHub Actions | Workflow review pending | Pending validation |
| CICD-09 | Establish complete dependency and secret scanning | Full CI enforcement of dependency and secret scanning has not been established by this review. | CI pipeline | Workflow review pending | Pending validation |

### 14.1 Supply-Chain Limitations

The presence of workflow directories, local security tools, ECR scanning configuration, or Lambda code-signing configuration does not establish a complete secure CI/CD pipeline.

The complete workflow must be reviewed and validated for:

- Dependency vulnerability scanning.
- Secret scanning.
- Container image scanning.
- Terraform security scanning.
- Test and build enforcement.
- Artifact integrity.
- Deployment identity and least privilege.
- Environment approval controls.
- Deployment failure handling.

These capabilities must not be represented as fully operational until the corresponding workflow implementation and execution evidence exist.

## 15. Consolidated Hardening and Validation Register

The following items are improvement opportunities or deployment dependencies. They are not all confirmed vulnerabilities.

| ID | Priority | Item | Classification | Required action |
|---|---|---|---|---|
| HR-01 | Critical deployment prerequisite | No AWS infrastructure has been deployed. | Validation limitation | Perform controlled deployment and verify actual resource configuration before making operational security claims. |
| HR-02 | High | Production frontend hosting and security headers are absent. | Missing deployment control | Select hosting architecture and implement HTTPS, CSP, HSTS, frame restrictions, and other appropriate response headers. |
| HR-03 | High | Production Cognito callback URLs and frontend origin are pending. | Deployment dependency | Configure and test exact production origins and callback/logout URLs. |
| HR-04 | High | WAF URI scope-down requires verification. | Configuration validation | Verify the deployed stage path and forwarded URI against the rate-limit rule. |
| HR-05 | High | Internal application traffic uses HTTP. | Transport hardening | Evaluate TLS between VPC Link, ALB, and application targets. |
| HR-06 | High | CI/CD security enforcement is not fully established. | Pipeline hardening | Complete and execute security gates for tests, dependencies, secrets, containers, and Terraform. |
| HR-07 | Medium | CloudTrail S3 data events are not configured. | Audit coverage limitation | Evaluate whether object-level data events are required and enable appropriate selectors if justified. |
| HR-08 | Medium | CloudTrail SNS KMS permission scope requires review. | IAM/KMS hardening | Confirm AWS service integration requirements and scope permissions appropriately. |
| HR-09 | Medium | FastAPI `/docs` and `/redoc` remain enabled. | Application hardening | Disable or restrict interactive API documentation in production. |
| HR-10 | Medium | Interface endpoints are present in only one private subnet. | Resilience improvement | Evaluate endpoint placement in both Availability Zones. |
| HR-11 | Medium | No NAT Gateway is configured. | Operational dependency | Validate EC2 bootstrap and package retrieval through the intended private connectivity design. |
| HR-12 | Medium | Browser tokens use local-storage-based Amplify behavior. | Browser security hardening | Evaluate an alternative token-storage strategy and its authentication, refresh, and usability implications. |
| HR-13 | Medium | PDF validation checks signatures rather than document structure or malware. | Document security improvement | Evaluate malware scanning and deeper document validation appropriate to the threat model. |
| HR-14 | Low | Pagination cursors are unsigned. | Defense-in-depth improvement | Consider signing cursors if future requirements justify the additional complexity. |
| HR-15 | Low | API Gateway X-Ray tracing is disabled. | Observability improvement | Evaluate distributed tracing while maintaining data-minimization requirements. |

## 16. Validation Evidence Summary

The following evidence was available during this review.

### 16.1 Backend Application

- Backend test suite: 931 passed, with 8 subtests, in the recorded full-suite run.
- Focused storage tests: 45 passed.
- Document service/API integration tests: 111 passed.
- Authentication regression tests: 12 passed.
- Stage C focused tests: 73 passed.
- Stage D unit tests: 74 passed.
- Stage D integration tests: 8 passed.

These are results from recorded test runs. They are not necessarily unique test counts and should not be summed to derive a total.

### 16.2 Frontend Application

- 157 tests passed across 11 test files in the recorded frontend baseline.
- ESLint passed.
- TypeScript and Vite production build passed.
- Authentication regression tests passed.

### 16.3 Infrastructure

- Terraform formatting checks passed.
- Terraform validation passed.
- Checkov 3.4.3 recorded result: 640 passed, 0 failed, 67 skipped.
- Existing DynamoDB `hash_key` deprecation warnings remain.

### 16.4 Container

Local container runtime validation confirmed the configured security properties, and application health endpoints returned HTTP 200.

### 16.5 AWS Deployment

No AWS infrastructure has been deployed.

The Terraform state contains zero managed resources. Therefore, the following have not been established:

- Live AWS security-group enforcement.
- Actual Cognito authentication against deployed resources.
- Actual KMS encryption behavior.
- Live S3 upload and download behavior.
- CloudTrail event delivery.
- CloudWatch alarm triggering.
- SNS notification delivery.
- WAF request blocking and rate limiting.
- Scheduled Lambda execution.
- EC2 bootstrap and application health in AWS.

## 17. Overall Control Assessment

The project has a broad set of application-level security controls, infrastructure definitions, and local validation evidence.

The strongest reviewed areas include:

- Backend authentication and authorization.
- Tenant-scoped data access.
- Transaction-level reviewer authorization.
- Document upload and download authorization.
- Exact-version S3 document handling.
- Scheduled document lifecycle processing.
- Container runtime restrictions.
- Terraform security configuration.
- Local backend and frontend automated testing.

The most significant remaining work concerns production deployment and operational validation, frontend hosting security, complete CI/CD enforcement, and selected infrastructure hardening opportunities.

No confirmed exploitable backend or frontend vulnerability was identified in the reviewed components. This conclusion is limited to the reviewed source code and configuration; it is not a guarantee that the complete system is vulnerability-free.

## 18. Review Boundaries

This document reflects the project state reviewed on 20 November 2026.

It does not claim:

- A completed AWS deployment.
- Successful live AWS security testing.
- Production readiness.
- Independent third-party penetration testing.
- Compliance certification.
- Guaranteed availability or disaster recovery.
- Complete malware detection for uploaded documents.
- Complete audit coverage of all AWS data-plane operations.
- Complete CI/CD security enforcement.

Future changes to the application, Terraform, IAM policies, workflows, or deployment architecture should trigger an appropriate review of the affected controls.

## 19. Conclusion

The Security Controls Matrix establishes traceability between the project's security objectives, implementation components, enforcement layers, and available validation evidence.

It provides a consolidated reference for subsequent security hardening, deployment validation, and operational readiness assessment.

The project should proceed to controlled AWS deployment only after the relevant deployment prerequisites and security hardening items have been reviewed. All controls must then be validated against actual AWS resources and application behavior before being described as operational.
