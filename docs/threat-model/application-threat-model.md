# Application Threat Model

**Project:** Secure Multi-Tenant Document Exchange Platform  
**Document:** Application Threat Model  
**Version:** 1.0  
**Methodology:** STRIDE  
**Status:** Architecture-based threat analysis  
**Cloud Platform:** Amazon Web Services  
**Region:** `ap-south-1`  
**Related Document:** `docs/architecture/application-architecture.md`

---

## 1. Purpose and Scope

This document identifies security threats affecting the Secure Multi-Tenant Document Exchange Platform and evaluates the controls implemented to mitigate them.

The platform is a multi-tenant document submission and review application. Users authenticate through Amazon Cognito, access application APIs through API Gateway, and interact with tenant-scoped submissions and documents.

The threat model focuses on:

- Authentication and session security.
- Authorization and tenant isolation.
- Submission and workflow integrity.
- Document upload and download security.
- S3 object and version management.
- DynamoDB data integrity.
- Application infrastructure and network boundaries.
- Scheduled Lambda workers.
- Audit logging and security monitoring.
- CI/CD and deployment artifact integrity.
- Frontend security.

The analysis uses STRIDE:

| Category | Meaning |
|---|---|
| Spoofing | Impersonating a user, service, or trusted component |
| Tampering | Unauthorized modification of data, configuration, or execution |
| Repudiation | Denying an action or making it difficult to establish accountability |
| Information Disclosure | Exposing sensitive information to unauthorized parties |
| Denial of Service | Making application resources or services unavailable |
| Elevation of Privilege | Gaining permissions beyond those intended |

This is an architecture and implementation-based threat assessment. It is not a penetration-test report or a claim of successful live AWS security validation.

## 2. System Overview

### 2.1 Application Components

The system consists of:

| Component | Responsibility |
|---|---|
| React frontend | User interface and authenticated API interaction |
| Amazon Cognito | User authentication and token issuance |
| API Gateway | Public API entry point and Cognito authorization |
| AWS WAF | Web request filtering and rate-based protection |
| VPC Link V2 | Private connectivity from API Gateway |
| Internal ALB | Private application traffic distribution |
| EC2 Auto Scaling Group | Application compute |
| Docker | Application container execution |
| FastAPI | Authentication validation, authorization, business logic |
| DynamoDB | Submission, membership, and audit records |
| S3 | Document and supporting object storage |
| KMS | Encryption key management |
| Lambda workers | Scheduled document lifecycle and JWKS operations |
| EventBridge Scheduler | Scheduled worker invocation |
| ECR | Container image storage |
| AWS Signer | Lambda artifact signing |
| CloudTrail | AWS account activity logging |
| CloudWatch | Monitoring, logs, metrics, and alarms |
| SNS | Security notifications |

### 2.2 User Roles

The application defines three primary roles:

- `SUBMITTER`
- `REVIEWER`
- `TENANT_ADMIN`

Roles are associated with tenant membership.

A user's permissions are not determined solely by the role name contained in a client-side request. The backend validates active membership, tenant association, and required role.

### 2.3 Security Objectives

The primary security objectives are:

1. Prevent cross-tenant data access.
2. Prevent unauthorized submission and document access.
3. Prevent privilege escalation through membership management.
4. Preserve workflow and document lifecycle integrity.
5. Protect authentication tokens and user identities.
6. Prevent unauthorized access to private S3 objects.
7. Restrict AWS service permissions using least privilege.
8. Maintain reliable audit evidence for relevant operations.
9. Prevent unauthorized modification of deployed application artifacts.
10. Detect and respond to suspicious AWS account activity.

## 3. Assets and Security Impact

The following assets require protection.

| Asset | Security importance | Primary protection |
|---|---|---|
| Cognito identities and tokens | Authentication and account access | Cognito, JWT validation |
| Tenant membership records | Authorization and tenant boundaries | DynamoDB conditions and backend checks |
| Submission records | Confidentiality and integrity | Tenant-scoped access and conditional updates |
| Document contents | Confidentiality and integrity | Private S3, KMS, presigned URLs |
| S3 object versions | Document integrity and lifecycle | Version validation and cleanup workers |
| Audit events | Accountability and investigation | Restricted DynamoDB permissions |
| KMS keys | Data confidentiality and encryption integrity | Key policies and IAM restrictions |
| Application container images | Application execution integrity | ECR, immutable tags, digest pinning |
| Lambda artifacts | Worker execution integrity | AWS Signer and code-signing enforcement |
| Terraform configuration | Infrastructure security | Review, validation, Checkov |
| CloudTrail records | AWS activity investigation | CloudTrail, KMS, S3, CloudWatch |
| Application configuration | Runtime security | Restricted IAM and protected configuration |
| Security alerts | Detection and response | CloudWatch alarms and SNS |

### 3.1 Impact Classification

The impact of a successful attack depends on the affected asset.

- **Critical:** Cross-tenant exposure of sensitive documents, compromise of encryption keys, or broad administrative privilege escalation.
- **High:** Unauthorized document modification, account takeover, audit manipulation, or compromise of application execution.
- **Medium:** Exposure of limited metadata, denial of service against an individual tenant, or incomplete security telemetry.
- **Low:** Non-sensitive operational information exposure or limited disruption without access to protected data.

These classifications describe potential impact, not confirmed incidents.

## 4. Trust Boundaries and Data Flows

### 4.1 Trust Boundaries

The system contains the following trust boundaries.

| Boundary | Components | Security concern |
|---|---|---|
| TB-1: User to frontend | Browser and React application | Untrusted user input, token exposure, browser compromise |
| TB-2: Frontend to identity provider | Browser and Cognito | Authentication integrity and token issuance |
| TB-3: Public API boundary | Browser, WAF, API Gateway | Unauthorized requests, abuse, malformed input |
| TB-4: Public-to-private network | API Gateway, VPC Link, internal ALB | Private ingress and transport protection |
| TB-5: Application authorization boundary | FastAPI and authenticated identity | BOLA, RBAC bypass, tenant isolation |
| TB-6: Application-to-data boundary | FastAPI, DynamoDB, S3, KMS | Unauthorized data access or modification |
| TB-7: Scheduled execution boundary | EventBridge, Lambda, SQS | Unauthorized invocation and lifecycle manipulation |
| TB-8: Deployment boundary | CI/CD artifacts, ECR, AWS Signer, Lambda | Artifact substitution and unauthorized deployment |
| TB-9: AWS control plane | IAM, CloudTrail, CloudWatch, KMS, SNS | Privileged account activity and audit integrity |

### 4.2 Primary Request Flow

```text
User Browser
    |
    | Authentication
    v
Amazon Cognito
    |
    | Access Token
    v
React Frontend
    |
    | HTTPS API Request
    v
AWS WAF
    |
    v
API Gateway REST API
    |
    | Cognito Authorizer
    v
VPC Link V2
    |
    v
Internal Application Load Balancer
    |
    v
Private EC2 Instance
    |
    v
FastAPI
    |
    +-----------> DynamoDB
    |
    +-----------> S3
    |
    +-----------> KMS
```

### 4.3 Document Upload Flow

```text
Submitter
    |
    v
FastAPI Authorization
    |
    | Validate tenant, ownership,
    | workflow state and file constraints
    v
DynamoDB Upload Reservation
    |
    v
Presigned S3 POST
    |
    v
Private S3 Bucket
    |
    v
Backend Completion Validation
    |
    | Validate metadata, encryption,
    | object key and exact VersionId
    v
DynamoDB Document Record
```

The browser does not receive general S3 permissions. It receives a short-lived upload authorization generated by the backend.

### 4.4 Scheduled Lifecycle Flow

```text
EventBridge Scheduler
    |
    v
Lambda Worker
    |
    +-----------> DynamoDB Candidate Query
    |
    +-----------> S3 Version Inspection
    |
    +-----------> Conditional DynamoDB Update
    |
    v
CloudWatch Logs / Metrics

Failures
    |
    v
Configured Retry and Failure Destinations
```

The lifecycle workers perform different operations:

- Stage A: Pending document expiry.
- Stage B: Document object cleanup.
- Stage C: Document metadata finalization.
- Stage D: Uploaded document version hygiene.

## 5. Threat Actors and Attack Assumptions

### 5.1 External Attacker

An unauthenticated attacker may attempt to:

- Discover exposed API endpoints.
- Exploit input validation weaknesses.
- Abuse upload endpoints.
- Enumerate resource identifiers.
- Perform request flooding.
- Exploit application or dependency vulnerabilities.

### 5.2 Malicious Authenticated User

An authenticated Submitter or Reviewer may attempt to:

- Access another tenant's records.
- Change resource identifiers to access another user's data.
- Bypass workflow restrictions.
- Reuse upload authorization.
- Abuse document download functionality.
- Manipulate browser requests.

### 5.3 Malicious Tenant Administrator

A Tenant Administrator may attempt to:

- Elevate their own role.
- Modify another tenant's membership.
- Access documents outside administrative permissions.
- Abuse membership-management functionality.
- Manipulate audit visibility.

### 5.4 Compromised Application Identity

An attacker who obtains application credentials or compromises the application execution environment may attempt to:

- Read accessible DynamoDB records.
- Access permitted S3 objects.
- Use available KMS permissions.
- Exfiltrate application data.
- Modify records within the application's IAM permissions.

### 5.5 Compromised AWS Identity

An attacker with an AWS IAM identity may attempt to:

- Modify security groups.
- Change IAM permissions.
- Disable logging.
- Modify CloudTrail.
- Access encrypted data.
- Change Lambda configuration or deployment artifacts.

### 5.6 Malicious or Compromised Dependency

A compromised application dependency or container image may attempt to:

- Execute malicious code.
- Exfiltrate environment configuration.
- Access application credentials.
- Modify application data.
- Exploit container runtime permissions.

## 6. STRIDE Threat Analysis

### 6.1 Spoofing

Spoofing involves impersonating an authenticated user, application component, or trusted AWS service.

| ID | Threat | Potential impact | Existing controls | Residual risk |
|---|---|---|---|---|
| S-01 | Attacker forges or modifies a JWT | Unauthorized API access | RS256 signature, issuer, expiration, token-use, client ID, subject, and scope validation | Compromised signing key or identity provider remains a high-impact risk |
| S-02 | Attacker reuses an expired access token | Unauthorized session reuse | JWT expiration validation and short token validity | Stolen unexpired tokens remain usable until expiry or other revocation controls take effect |
| S-03 | Attacker impersonates another tenant member | Unauthorized tenant access | Strong membership checks and tenant-scoped authorization | Depends on identity-provider and account security |
| S-04 | Attacker guesses or substitutes a submission ID | Unauthorized resource access | Tenant-scoped repository access and ownership checks | Requires continued regression testing across endpoints |
| S-05 | Attacker invokes a scheduled worker as an unauthorized principal | Unauthorized lifecycle processing | Dedicated Lambda roles and configured service invocation | Live IAM and invocation behavior not validated |

#### Existing Mitigations

- Backend validates access-token claims and signature.
- Browser API client requires the expected API scope.
- Cognito authorizer protects API Gateway methods.
- Backend independently validates tokens.
- Membership authorization checks active membership and tenant association.
- Lambda workers use dedicated execution roles.
- Worker artifacts are configured for AWS Signer code-signing enforcement.

#### Residual Risks

- Account compromise can result in legitimate token issuance to an attacker.
- Browser token storage is JavaScript-accessible through the default Amplify browser storage implementation.
- Production authentication behavior has not been validated against deployed Cognito resources.
- Worker invocation permissions require live deployment verification.

### 6.2 Tampering

Tampering involves unauthorized modification of application records, document contents, workflow state, infrastructure, or deployment artifacts.

| ID | Threat | Potential impact | Existing controls | Residual risk |
|---|---|---|---|---|
| T-01 | User modifies a submission belonging to another tenant | Cross-tenant data modification | Tenant-scoped authorization and conditional repository operations | New endpoints must preserve the same authorization model |
| T-02 | User bypasses workflow transitions | Unauthorized approval or rejection | Explicit state transitions, version checks, conditional transactions | Live concurrent behavior not validated |
| T-03 | Reviewer membership is revoked during a transition | Unauthorized workflow modification | Transaction-level membership condition check | Requires deployed DynamoDB behavior validation |
| T-04 | Attacker modifies uploaded document content | Document integrity compromise | Exact S3 VersionId validation and version-specific downloads | Malware and deeper content inspection are not implemented |
| T-05 | Attacker modifies a Lambda deployment artifact | Malicious worker execution | AWS Signer and enforced Lambda code-signing configuration | Signing pipeline execution and live deployment enforcement not validated |
| T-06 | Attacker modifies application infrastructure | Network or privilege compromise | Terraform configuration and IAM restrictions | Deployment-role governance and approval controls require operational validation |
| T-07 | Lifecycle worker deletes an unintended object version | Document loss or integrity compromise | Exact-key filtering, version validation, conditional DynamoDB finalization | AWS service behavior has not been live-tested |

#### Existing Mitigations

- DynamoDB composite keys and tenant-scoped queries.
- Conditional updates and transactions.
- Submission ownership checks.
- Reviewer membership condition checks during workflow transitions.
- Exact S3 object-key validation.
- Exact object-version validation.
- Presigned upload policies enforce expected key, content type, encryption, and size.
- Stage C verifies that the object key is empty before metadata deletion.
- Stage D preserves the accepted document version and verifies remaining versions.
- Container images are pulled using an immutable digest.
- ECR tags are immutable.
- Lambda code signing is configured to enforce trusted artifacts.

#### Residual Risks

- S3 version cleanup depends on correct AWS permissions and service behavior.
- Application and worker tests use local test environments rather than live AWS.
- No malware scanning is currently established.
- Terraform deployment-role access governance is not yet validated.
- Artifact signing and deployment enforcement need live integration testing.

### 6.3 Repudiation

Repudiation involves denying an action or preventing investigators from establishing who performed it.

| ID | Threat | Potential impact | Existing controls | Residual risk |
|---|---|---|---|---|
| R-01 | User denies modifying a submission | Reduced accountability | Application audit events and authenticated user identity | Audit event completeness must be verified across all sensitive operations |
| R-02 | AWS administrator denies changing IAM permissions | Inability to investigate privilege changes | Multi-region CloudTrail management events and CloudWatch metric filters | No live delivery validation |
| R-03 | Attacker modifies application audit records | Loss of investigation evidence | Application role lacks audit UpdateItem and DeleteItem permissions | A sufficiently privileged AWS administrator may still alter underlying infrastructure or records |
| R-04 | Attacker disables CloudTrail | Reduced visibility | CloudTrail tampering metric filter and alarm | Detection and notification delivery are not live-validated |
| R-05 | Logs are deleted or expire before investigation | Loss of evidence | S3 versioning, CloudTrail validation, configured retention | Retention is finite and immutable storage is not established |

#### Existing Mitigations

- Application audit events include authenticated actor context.
- Audit records are tenant-scoped.
- Application IAM permissions restrict audit modification.
- CloudTrail captures read and write management events.
- CloudTrail log-file validation is enabled.
- CloudTrail logs are delivered to S3 and CloudWatch Logs.
- CloudTrail tampering events have dedicated metric filters and alarms.
- CloudWatch log groups have configured retention.

#### Residual Risks

- CloudTrail data events are not configured in the reviewed trail.
- Application audit completeness has not been proven through a full production workflow.
- S3 versioning does not provide the same guarantees as S3 Object Lock.
- CloudTrail and SNS delivery have not been validated in AWS.
- Operational investigation and incident-response procedures are not yet validated.

### 6.4 Information Disclosure

Information disclosure involves unauthorized exposure of documents, identity information, application metadata, tokens, logs, or encryption material.

| ID | Threat | Potential impact | Existing controls | Residual risk |
|---|---|---|---|---|
| I-01 | Submitter reads another user's submission | Confidentiality breach | Tenant and ownership checks | Endpoint regression remains possible |
| I-02 | User accesses another tenant's documents | Cross-tenant data exposure | Tenant-scoped authorization and backend-generated S3 keys | Live cross-tenant testing remains required |
| I-03 | Tenant Administrator downloads document contents | Privilege misuse | Tenant Administrator denied document-content authorization | Must be maintained as endpoints evolve |
| I-04 | Attacker steals presigned URLs | Unauthorized temporary document access | Short-lived URLs and exact object/version scoping | URLs are bearer credentials until expiration |
| I-05 | Public S3 access exposes documents | Broad data exposure | Block Public Access, bucket ownership controls, private bucket policy | Live bucket policy and access behavior not validated |
| I-06 | Sensitive information appears in application logs | Confidentiality breach | Application logging avoids record values; API access logs exclude bodies and authorization headers | Exception traceback content requires continued review |
| I-07 | Browser XSS exposes authentication tokens | Account compromise | React text rendering and no identified unsafe HTML sinks | Browser storage remains JavaScript-accessible |
| I-08 | Weak encryption policy permits plaintext transport | Data exposure | S3 policies deny insecure transport | Internal ALB and target traffic use HTTP |
| I-09 | KMS permissions allow unintended data decryption | Confidentiality breach | Restricted IAM and key policies | Live key-policy evaluation remains pending |

#### Existing Mitigations

- Private S3 bucket.
- S3 Block Public Access.
- Bucket-owner-enforced ownership.
- SSE-KMS encryption.
- Bucket policies requiring the expected KMS key.
- TLS enforcement for S3 requests.
- Short-lived upload and download URLs.
- Exact S3 VersionId binding for downloads.
- Backend tenant and ownership checks.
- Application IAM permissions restricted to required object operations.
- KMS permissions scoped by service and encryption context where configured.
- API Gateway access logs avoid logging request bodies and authorization headers.

#### Residual Risks

- Presigned URLs can be shared or stolen before expiration.
- Browser-accessible token storage increases the impact of successful XSS.
- Internal HTTP transport remains a deployment hardening concern.
- Malware scanning is not implemented.
- No production frontend Content Security Policy or security-header configuration exists.
- CloudTrail data-event coverage is not configured.
- Live S3 and KMS access policies have not been validated.

### 6.5 Denial of Service

Denial of Service involves exhausting application, network, database, storage, or worker resources.

| ID | Threat | Potential impact | Existing controls | Residual risk |
|---|---|---|---|---|
| D-01 | Attacker floods public API endpoints | API unavailability and increased cost | AWS WAF rate-based rule and API Gateway | Rate limiting is IP-based and effective URI coverage needs verification |
| D-02 | Attacker uploads excessively large files | Storage and compute exhaustion | 10 MiB document limit and presigned POST size conditions | Live S3 policy enforcement not validated |
| D-03 | Attacker repeatedly requests presigned uploads | Increased S3 object versions | Upload reservations and Stage D version hygiene | URL replay can still create extra versions |
| D-04 | Attacker creates excessive database operations | DynamoDB cost and availability impact | Tenant-scoped queries and conditional operations | No complete application-level per-user rate-limit control established |
| D-05 | Worker receives excessive lifecycle candidates | Worker timeout or backlog | Bounded batch sizes, time checks, concurrency limits | Large backlogs may require operational intervention |
| D-06 | S3 version history grows beyond cleanup limits | Cleanup failure and storage accumulation | Stage D maximum 5,000 versions per document and fail-closed behavior | Manual operational remediation may be required |
| D-07 | Private EC2 bootstrap cannot retrieve dependencies | Instance startup failure | S3, ECR, and other VPC endpoints | Docker package repository access needs verification without NAT |
| D-08 | AWS service cost exhaustion | Budget overrun or service disruption | $20 monthly budget and configured alerts | Budget alerts are not hard spending caps |

#### Existing Mitigations

- AWS WAF managed rule groups.
- WAF rate-based rule.
- API Gateway request entry point.
- Document size and type restrictions.
- Presigned upload expiry.
- Bounded Lambda batch processing.
- Lambda execution time limits.
- Reserved concurrency of one for reviewed lifecycle workers.
- SQS failure destinations and Scheduler dead-letter queues.
- S3 version-count safety limit.
- AWS budget alerts.

#### Residual Risks

- The WAF rule aggregates by source IP rather than authenticated tenant or user.
- Its URI scope-down condition requires routing verification.
- A compromised or abusive authenticated user may still consume application resources.
- A $20 budget alert does not automatically prevent further charges.
- NAT-free bootstrap and package retrieval need deployment testing.
- No comprehensive application-wide per-user quota system has been established.

### 6.6 Elevation of Privilege

Elevation of Privilege involves obtaining permissions beyond the intended role or identity.

| ID | Threat | Potential impact | Existing controls | Residual risk |
|---|---|---|---|---|
| E-01 | Submitter changes their own role | Unauthorized reviewer or administrator access | Backend membership administration restrictions | Regression testing required |
| E-02 | Tenant Administrator promotes themselves | Tenant privilege escalation | Self-modification and administrator assignment restrictions | Live transactional behavior not validated |
| E-03 | Tenant Administrator modifies another tenant | Cross-tenant administrative compromise | Tenant-scoped membership operations | New administrative endpoints must follow same model |
| E-04 | Reviewer transitions a submission without active membership | Unauthorized approval or rejection | Transaction-level membership condition check | Live DynamoDB transaction behavior not validated |
| E-05 | Application role obtains excessive AWS permissions | Broad data or infrastructure access | Scoped IAM policies and separate Lambda roles | Effective permissions need live IAM validation |
| E-06 | Compromised container accesses host resources | Host compromise | Non-root execution, read-only root, dropped capabilities, no-new-privileges, resource limits | Container isolation does not eliminate kernel/runtime vulnerabilities |
| E-07 | Attacker deploys an unsigned Lambda artifact | Malicious worker execution | Lambda code-signing enforcement configuration | Signing and deployment behavior not live-validated |
| E-08 | AWS identity modifies CloudTrail or security controls | Security monitoring compromise | CloudTrail tampering detection and least-privilege configuration | Privileged identity governance and alert delivery remain unvalidated |

#### Existing Mitigations

- Backend role and membership enforcement.
- Transactional membership checks.
- Explicit workflow transition validation.
- Separate IAM roles for application and Lambda workers.
- Restricted DynamoDB permissions.
- No wildcard DynamoDB application permissions in the reviewed application policy.
- Audit table write/query-only application permissions.
- Restricted S3 object permissions.
- KMS service and encryption-context restrictions.
- Non-root application container.
- Lambda code-signing configuration.

#### Residual Risks

- AWS administrators with sufficiently broad permissions may alter infrastructure controls.
- IAM effective permissions have not been verified in a deployed account.
- Deployment pipeline governance and approval enforcement require separate validation.
- Container hardening reduces exposure but does not provide a complete security boundary against host-level vulnerabilities.

## 7. Threat Assessment by Component

| Component | Primary threats | Key controls | Remaining concern |
|---|---|---|---|
| Cognito | Spoofing, token theft | JWT validation, short token lifetime, required scope | Account compromise and browser token exposure |
| Frontend | Information disclosure, spoofing | Protected routes, API scope checks, React text rendering | No production CSP or hosting security headers |
| API Gateway | DoS, spoofing | Cognito authorizer, WAF, access logs | WAF path coverage and live behavior |
| VPC Link and ALB | Information disclosure, unauthorized ingress | Internal ALB, security-group restrictions | Internal HTTP transport |
| FastAPI | BOLA, privilege escalation, tampering | Server-side authorization and validation | Continuous regression testing required |
| DynamoDB | Tampering, information disclosure | Tenant keys, conditional writes, transactions, IAM | Live IAM and transaction validation |
| S3 | Information disclosure, tampering | Private bucket, SSE-KMS, presigned URLs, versioning | Malware scanning and live policy validation |
| Lambda workers | Tampering, DoS, privilege escalation | Dedicated roles, bounded execution, retries, signing | Live execution and failure behavior |
| ECR and containers | Tampering, privilege escalation | Immutable tags, digest pinning, container restrictions | Runtime and host vulnerability exposure |
| KMS | Information disclosure | Key policies, rotation, encryption contexts | Effective permissions and service integration |
| CloudTrail | Repudiation, tampering | Log-file validation, S3 and CloudWatch delivery, alarms | No live delivery proof or data events |
| SNS and CloudWatch | Repudiation, detection failure | Encrypted topics, metric filters, alarms | Notification delivery and response validation |

## 8. Existing Security Control Summary

The following controls have implementation or configuration evidence.

| Control | Implementation status | Validation status |
|---|---|---|
| JWT signature and claim validation | Implemented | Locally tested |
| Cognito API scope enforcement | Implemented | Locally tested |
| Tenant membership authorization | Implemented | Locally tested |
| Submission ownership checks | Implemented | Locally tested |
| Reviewer transactional authorization | Implemented | Locally tested |
| Tenant Administrator restrictions | Implemented | Locally tested |
| Conditional workflow transitions | Implemented | Locally tested |
| Presigned S3 upload restrictions | Implemented | Locally tested |
| Exact S3 version validation | Implemented | Locally tested |
| S3 private bucket and encryption | Terraform configured | Not live-validated |
| DynamoDB encryption and PITR | Terraform configured | Not live-validated |
| Application IAM least privilege | Terraform configured | Static review |
| VPC security groups | Terraform configured | Static review |
| API Gateway and WAF | Terraform configured | Not live-validated |
| CloudTrail monitoring | Terraform configured | Not live-validated |
| SNS security notifications | Terraform configured | Not live-validated |
| Lambda code signing | Terraform configured | Not live-validated |
| Container hardening | Implemented | Locally tested |
| Frontend authentication handling | Implemented | Automated tests |
| Frontend production security headers | Pending hosting layer | Not validated |
| Internal HTTPS | Not configured | Not validated |

## 9. Residual Risk Register

The following risks remain after considering the implemented controls.

| ID | Residual risk | Severity | Recommended treatment |
|---|---|---|---|
| RR-01 | Browser-accessible token storage increases impact of XSS | Medium | Evaluate token storage options and maintain strict frontend security controls |
| RR-02 | Production frontend hosting and security headers are absent | High | Select hosting layer and configure CSP and security headers |
| RR-03 | Internal application traffic uses HTTP | Medium | Introduce TLS for internal hops and validate certificate handling |
| RR-04 | WAF rate-limit path coverage has not been verified | High | Confirm API Gateway stage and backend path mapping |
| RR-05 | CloudTrail data events are not configured | Medium | Decide whether S3 object-level auditing is required |
| RR-06 | CloudTrail SNS KMS permission scope needs review | Medium | Verify AWS service requirements and tighten policy where possible |
| RR-07 | Private EC2 bootstrap package retrieval is not validated | High | Test package installation and dependency retrieval without NAT |
| RR-08 | Interface endpoints exist only in one private subnet | Medium | Evaluate multi-AZ endpoint placement |
| RR-09 | Malware scanning and deeper document validation are absent | Medium | Evaluate asynchronous document scanning |
| RR-10 | S3 Object Lock is not configured | Medium | Evaluate immutable retention requirements for audit records |
| RR-11 | WAF IP-based throttling does not provide per-user quotas | Medium | Evaluate authenticated user and tenant-level limits |
| RR-12 | CloudTrail, SNS, and Lambda operational behavior is not live-tested | High | Perform controlled deployment and integration validation |
| RR-13 | Deployment-role governance is not fully validated | High | Establish least-privilege deployment identity and approval controls |
| RR-14 | Application-wide resource quotas are not established | Medium | Define per-tenant and per-user operational limits |

Severity indicates the potential importance of addressing the risk before production deployment. It is not a statement that exploitation has occurred.

## 10. Security Testing Requirements

The following tests should be performed before production deployment.

### 10.1 Authentication

- Reject expired tokens.
- Reject invalid signatures.
- Reject incorrect issuer.
- Reject ID tokens where access tokens are required.
- Reject incorrect client IDs.
- Reject missing API scope.
- Reject malformed JWT headers and claims.
- Verify behavior when JWKS data is unavailable or stale.

### 10.2 Tenant Isolation

- Submitter A cannot access Submitter B's submission.
- Tenant A cannot access Tenant B's submission.
- Reviewer cannot review another tenant's submission.
- Tenant Administrator cannot access document contents solely through administrative permissions.
- Inactive members cannot perform protected operations.
- Changing tenant or submission identifiers cannot bypass backend authorization.

### 10.3 Membership and Privilege Escalation

- Submitter cannot change their own role.
- Tenant Administrator cannot modify their own membership.
- Tenant Administrator cannot modify another tenant's members.
- Tenant Administrator cannot assign another user the Tenant Administrator role through the ordinary role-change operation.
- Existing Tenant Administrators cannot be modified through prohibited member-management transitions.
- Concurrent membership revocation and workflow transitions preserve authorization correctness.

### 10.4 Document Security

- Reject unsupported MIME types.
- Reject oversized files.
- Reject incorrect S3 object keys.
- Reject uploads without required SSE-KMS encryption.
- Reject incorrect KMS key usage.
- Reject missing or invalid S3 VersionId values.
- Reject unauthorized document downloads.
- Verify that download URLs reference the accepted object version.
- Verify upload URL expiry and replay behavior.
- Confirm that cleanup workers preserve the accepted document version.

### 10.5 Infrastructure Security

- Confirm API Gateway is the intended public entry point.
- Confirm the ALB is internal.
- Confirm security groups permit only intended traffic.
- Confirm private instances have no public IP.
- Confirm S3 public access is blocked.
- Confirm DynamoDB encryption and PITR.
- Confirm KMS key policies and effective IAM permissions.
- Confirm CloudTrail delivery and log-file validation.
- Confirm WAF rules cover the intended API paths.
- Confirm Lambda code-signing enforcement.
- Confirm failure destinations and alarms work.

### 10.6 Operational Security

- Validate EC2 bootstrap in the NAT-free network.
- Validate scheduled Lambda execution.
- Simulate worker failures and retry exhaustion.
- Verify SQS failure destinations and dead-letter queues.
- Verify CloudWatch alarm transitions.
- Verify SNS notification delivery.
- Confirm log retention and access restrictions.
- Confirm cost alerts and budget notifications.

## 11. Validation Evidence and Limitations

### 11.1 Local Application Testing

Recorded backend baseline:

- 931 tests passed.
- 8 subtests passed.

Recorded frontend baseline:

- 157 tests passed across 11 test files.
- ESLint passed.
- TypeScript and Vite production build passed.

### 11.2 Infrastructure Validation

Recorded Terraform validation:

- `terraform fmt -check` passed.
- `terraform validate` passed.
- Checkov: 640 passed, 0 failed, 67 skipped.

Documented Checkov exceptions are maintained in:

`docs/security/checkov-exceptions.md`

### 11.3 Container Validation

The application container was locally tested for:

- Non-root execution.
- Read-only root filesystem.
- Dropped capabilities.
- No-new-privileges.
- Memory and PID limits.
- Health endpoint availability.

### 11.4 Validation Limitations

The AWS infrastructure has not been deployed.

Therefore, this threat model does not claim:

- Successful live AWS authorization.
- Successful live S3 or DynamoDB access enforcement.
- Successful live KMS key-policy enforcement.
- Successful live CloudTrail delivery.
- Successful live SNS notification delivery.
- Successful live WAF blocking or rate limiting.
- Successful live Lambda scheduling and retries.
- Successful live code-signing enforcement.
- Successful production penetration testing.

The current evidence establishes implementation and local validation, not production security assurance.

## 12. Conclusion

The platform has been designed with multiple layers of security enforcement.

The most significant security boundaries are:

1. Cognito authentication and backend JWT validation.
2. Tenant-scoped authorization and ownership checks.
3. Conditional DynamoDB transactions for sensitive state changes.
4. Private S3 storage and short-lived, constrained presigned URLs.
5. Least-privilege IAM roles.
6. Private application networking.
7. Container and Lambda deployment-integrity controls.
8. CloudTrail and CloudWatch security monitoring.

The most important remaining deployment and hardening priorities are:

- Production frontend hosting and security headers.
- Internal TLS.
- Verification of WAF URI coverage.
- Private EC2 bootstrap validation without NAT.
- CloudTrail and SNS live integration validation.
- Deployment-role governance.
- Operational validation of lifecycle workers and their failure handling.

The current project demonstrates substantial application and infrastructure security implementation. Final security assurance requires controlled deployment, live integration testing, and validation of the remaining risks.

---

**Document maintenance:** Reassess this threat model when authentication, authorization, data flows, infrastructure, or deployment architecture changes materially.
