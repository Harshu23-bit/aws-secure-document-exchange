# Secure Multi-Tenant Document Exchange Platform

**Document:** Application Architecture Specification  
**Version:** 1.1  
**Status:** Substantially implemented and locally validated — AWS deployment and live validation pending  
**Platform:** Amazon Web Services  
**Region:** `ap-south-1` (Mumbai)  
**Infrastructure as Code:** Terraform  
**Application:** FastAPI, React, TypeScript

---

## 1. Project Overview

The Secure Multi-Tenant Document Exchange Platform is a cloud-based application designed to support secure document submission, review, and administrative management across multiple independent tenants.

The platform provides role-based workflows while enforcing tenant isolation at the application, authorization, database, and object-storage layers.

The primary security objectives are:

- Prevent unauthorized access to documents and submissions belonging to another tenant.
- Enforce server-side authorization for every protected operation.
- Restrict application permissions according to least privilege.
- Protect document uploads and downloads through short-lived presigned URLs.
- Encrypt application data and audit records.
- Maintain an application audit trail for security-relevant operations.
- Detect suspicious AWS account activity through centralized monitoring.
- Automate document lifecycle management and uploaded-object version hygiene.
- Provide a reproducible infrastructure deployment through Terraform.

The application is designed as a portfolio-grade cloud security implementation. Its infrastructure and application code have undergone substantial local validation, but the AWS environment has not been deployed or live-validated.

## 2. Functional Requirements

### 2.1 Submitter

A Submitter can:

- Authenticate through Amazon Cognito.
- View tenants to which the user belongs.
- Select an authorized tenant.
- Create document submissions.
- Upload supported documents.
- View the status of their own submissions.
- View permitted submission metadata.
- Complete submission workflows where permitted.

A Submitter must not be able to:

- Access another user's submissions.
- Access submissions belonging to another tenant.
- Change their own role.
- Modify reviewer or tenant-administrator permissions.
- Bypass document upload validation.
- Access an object through an unauthorized S3 key or version.

### 2.2 Reviewer

A Reviewer can:

- View submissions within their authorized tenant.
- Review eligible documents.
- Download documents when the workflow state permits.
- Perform permitted workflow transitions.
- Generate audit events through review actions.

Reviewer authorization is checked against active tenant membership. The workflow transition also performs a transaction-level membership condition check to prevent a stale or revoked membership from authorizing a state transition.

A Reviewer must not be able to:

- Access another tenant's submissions.
- Review submissions outside their tenant.
- Perform transitions not permitted by the workflow.
- Continue performing authorized operations after membership deactivation.
- Modify tenant membership or administrator privileges.

### 2.3 Tenant Administrator

A Tenant Administrator can:

- View tenant membership information.
- List members within their tenant.
- Change permitted member roles.
- Deactivate eligible tenant members.
- View tenant-scoped audit events.

Administrative permissions do not automatically grant access to document contents.

A Tenant Administrator must not be able to:

- Promote themselves.
- Modify their own membership through the administrative endpoints.
- Modify another tenant's members.
- Assign the Tenant Administrator role through ordinary member-role changes.
- Modify another existing Tenant Administrator.
- Deactivate an already inactive member through an unsupported transition.
- Download document contents solely because of the administrative role.

The backend enforces these restrictions independently of the frontend.

## 3. Security Requirements

### 3.1 Authentication

Amazon Cognito User Pools provide user authentication.

The browser application uses an OAuth 2.0 Authorization Code flow with a public Cognito application client.

The API requires an access token with the resource-server scope:

`cloudsec-api/access`

The backend independently validates JWTs, including:

- RS256 signature.
- Issuer.
- Expiration.
- Issued-at timestamp.
- Subject.
- Token use.
- Browser application client ID.
- Required API scope.

The backend does not treat frontend authentication state as an authorization boundary.

### 3.2 Authorization

The application implements role-based access control using:

- `SUBMITTER`
- `REVIEWER`
- `TENANT_ADMIN`

Authorization decisions are tenant-scoped and enforced server-side.

The application validates:

- Authenticated identity.
- Active tenant membership.
- Tenant association.
- Required role.
- Submission ownership where applicable.
- Workflow state and version.
- Resource identity and object-key relationships.

### 3.3 Tenant Isolation

Tenant isolation is enforced at multiple layers:

1. Authentication establishes the caller's identity.
2. Membership authorization verifies the user's active tenant relationship.
3. Application services validate tenant ownership and role requirements.
4. Repository operations use tenant-scoped DynamoDB keys and indexes.
5. S3 object keys are generated by the backend using validated resource identifiers.
6. Workflow transactions enforce relevant state, ownership, and membership conditions.

The tenant identifier supplied by the frontend is not trusted as proof of authorization.

### 3.4 Data Protection

Application documents are stored in a private S3 bucket.

Controls include:

- S3 Block Public Access.
- Bucket-owner-enforced object ownership.
- Versioning.
- Default SSE-KMS encryption.
- Bucket policy enforcement of the required KMS key.
- Denial of insecure transport.
- Restricted application IAM permissions.
- Short-lived presigned upload and download URLs.

DynamoDB tables use customer-managed KMS encryption and point-in-time recovery.

### 3.5 Auditability

Security-relevant application operations produce application audit events.

AWS account activity is captured through CloudTrail management events and forwarded to CloudWatch Logs.

The architecture separates application-level audit records from AWS control-plane activity.

DynamoDB point-in-time recovery and S3 versioning provide recovery capabilities but do not independently establish immutable audit storage.

## 4. Technology Stack

| Component | Technology |
|---|---|
| Frontend | React, TypeScript, Vite |
| UI styling | Tailwind CSS |
| Backend | FastAPI |
| API server | Uvicorn |
| Authentication | Amazon Cognito |
| API ingress | Amazon API Gateway REST API |
| API protection | AWS WAF |
| Private application ingress | API Gateway VPC Link V2 |
| Load balancing | Internal Application Load Balancer |
| Compute | Amazon EC2 Auto Scaling Group |
| Container runtime | Docker |
| Container registry | Amazon ECR |
| Primary database | Amazon DynamoDB |
| Document storage | Amazon S3 |
| Encryption | AWS KMS |
| Audit logging | AWS CloudTrail |
| Application monitoring | Amazon CloudWatch |
| Notifications | Amazon SNS |
| Scheduled processing | Amazon EventBridge Scheduler |
| Server management | AWS Systems Manager |
| Lambda deployment integrity | AWS Signer and Lambda Code Signing |
| Infrastructure as Code | Terraform |
| Infrastructure scanning | Checkov |
| Application testing | Pytest, Vitest, Testing Library |
| Container scanning | Trivy |

## 5. High-Level Architecture

The platform uses a public API Gateway entry point and a private application-processing tier.

```text
                       USERS
                         |
                         |
                  React / TypeScript
                         |
                         |
                 Amazon Cognito
                  Authentication
                         |
                         |
                 Public HTTPS API
                         |
                         v
                 AWS WAF Web ACL
                         |
                         v
              API Gateway REST API
                    Regional
                         |
                Cognito Authorizer
                Required API Scope
                         |
                         v
                 VPC Link V2
                         |
                         v
               Internal Application
                  Load Balancer
                         |
                         v
                 Private EC2 ASG
                   Docker Runtime
                         |
                         v
                    FastAPI
                         |
             +-----------+-----------+
             |           |           |
             v           v           v
          DynamoDB       S3          KMS
             |
             v
        Audit Events

       Supporting security services:
       CloudTrail / CloudWatch / SNS
       EventBridge Scheduler / Lambda
       AWS Signer / ECR / VPC Endpoints
```

The frontend is a separate application component. A production frontend hosting service and its associated security headers have not yet been configured.

## 6. Application Roles and Permissions

### 6.1 SUBMITTER

The Submitter role is limited to submission creation, ownership-scoped access, and document upload operations.

Submission ownership is validated by the backend. A user cannot gain access merely by changing a submission identifier in a request.

### 6.2 REVIEWER

The Reviewer role permits tenant-scoped review and eligible document download operations.

Reviewer membership is checked during workflow transitions, including through a DynamoDB transaction condition check.

### 6.3 TENANT_ADMIN

The Tenant Administrator role provides tenant membership administration and tenant-scoped audit visibility.

It does not automatically provide document-content access.

### 6.4 Administrative Enforcement

Role changes and member deactivation are protected by backend checks and transactional conditions.

The application prevents self-modification, cross-tenant modification, unauthorized administrator assignment, and modification of existing tenant administrators through the ordinary member-management workflow.

Frontend role-aware controls improve usability but are not the security enforcement mechanism.

## 7. Tenant Isolation and Data Model

### 7.1 DynamoDB Tables

The infrastructure defines three DynamoDB tables.

| Table | Purpose |
|---|---|
| `cloudsec-submissions-dev` | Submission and document-related records |
| `cloudsec-tenant-memberships-dev` | Tenant membership and role information |
| `cloudsec-audit-events-dev` | Application audit events |

All three use on-demand billing, customer-managed KMS encryption, and point-in-time recovery.

### 7.2 Submission Table Indexes

The submissions table includes:

- `OwnerIndex`
- `TenantStatusIndex`
- `PendingDocumentExpiryIndex`
- `PendingDocumentCleanupIndex`

The first two support tenant and owner-scoped application queries.

The latter two are sparse indexes used by scheduled document lifecycle workers.

### 7.3 Membership Table

The membership table includes the `TenantMembersIndex` GSI for tenant member queries.

Membership authorization checks identity, tenant association, active status, and role.

### 7.4 Audit Table

The audit table includes the `TenantAuditIndex` GSI for tenant-scoped audit queries.

The application role is permitted to create and query audit records but is not granted audit-record update or delete permissions.

### 7.5 Transactional Consistency

DynamoDB transactions are used where multiple related state changes must succeed together.

Examples include:

- Submission workflow transitions and audit-event creation.
- Reviewer membership validation during workflow transitions.
- Tenant membership administration and associated audit events.
- Document lifecycle state changes and relevant counter updates.

Conditional expressions protect against stale state and conflicting concurrent operations.

## 8. Network Architecture and Trust Boundaries

### 8.1 VPC

The application VPC uses:

`10.20.0.0/16`

It contains:

| Subnet | CIDR | Availability Zone |
|---|---|---|
| Public A | `10.20.1.0/24` | `ap-south-1a` |
| Public B | `10.20.2.0/24` | `ap-south-1b` |
| Private A | `10.20.11.0/24` | `ap-south-1a` |
| Private B | `10.20.12.0/24` | `ap-south-1b` |

The public subnets have an Internet Gateway route.

The private application subnets do not have a default route to the Internet.

No NAT Gateway is configured.

### 8.2 API Ingress

The public API entry point is an API Gateway Regional REST API.

The request path is:

1. The client authenticates through Cognito.
2. The client sends an access token to API Gateway.
3. AWS WAF evaluates the request.
4. API Gateway's Cognito authorizer validates the configured authorization requirements.
5. API Gateway forwards authorized traffic through VPC Link V2.
6. The internal ALB receives traffic from the VPC Link security group.
7. The ALB forwards traffic to the private EC2 application tier.
8. FastAPI performs independent token validation and application-level authorization.

### 8.3 Security Group Boundaries

The intended application traffic flow is:

| Source | Destination | Port |
|---|---|---:|
| VPC Link security group | ALB security group | TCP 80 |
| ALB security group | Application security group | TCP 8080 |
| Application security group | Required VPC endpoints | TCP 443 |

The ALB accepts inbound traffic only from the VPC Link security group.

The application instances accept inbound traffic only from the ALB security group.

The application instances do not receive direct public ingress.

### 8.4 Internal Transport Encryption Limitation

The API Gateway-to-ALB integration and ALB-to-instance target traffic currently use HTTP.

The ALB is internal and security-group restricted, but this does not provide end-to-end transport encryption across those internal hops.

An HTTPS backend and certificate strategy remain deployment hardening requirements.

### 8.5 VPC Endpoints

The private network includes:

- S3 Gateway endpoint.
- DynamoDB Gateway endpoint.
- ECR API interface endpoint.
- ECR Docker Registry interface endpoint.
- Systems Manager interface endpoint.
- Systems Manager Messages interface endpoint.

The interface endpoints are currently configured in private subnet A rather than both Availability Zones.

This is an availability and resilience limitation. It should not be described as multi-AZ endpoint deployment.

The endpoint architecture is intended to support private access to required AWS services without a NAT Gateway.

### 8.6 CORS

API Gateway provides unauthenticated MOCK OPTIONS integrations for browser preflight requests.

The configured allowed headers are:

- `Authorization`
- `Content-Type`
- `Accept`

The configured methods are:

- `GET`
- `POST`
- `PUT`
- `PATCH`
- `DELETE`
- `OPTIONS`

Gateway 4XX and 5XX responses include CORS headers.

FastAPI also implements CORS middleware.

The development frontend origin is:

`http://localhost:5173`

Credentialed cross-origin requests are not enabled.

Production frontend origin configuration must be completed before deployment.

## 9. Document Storage and Upload Security

### 9.1 Object Storage

Documents are stored in a private, versioned S3 bucket.

The application object-key format is:

```text
tenants/{tenant_id}/submissions/{submission_id}/{document_id}
```

Object identifiers are generated and validated by the backend.

### 9.2 Upload Workflow

The upload workflow uses a backend-generated presigned S3 POST request.

The backend enforces:

- Supported file types: PDF, JPEG, and PNG.
- Maximum document size: 10 MiB.
- Exact object key.
- Exact content type.
- Required SSE-KMS encryption.
- Required KMS key.
- Short-lived upload authorization.

The upload reservation is stored in DynamoDB.

After the client uploads the object, the backend verifies the resulting object metadata and exact S3 version before accepting the document.

The document record is not considered successfully uploaded merely because the client reports upload success.

### 9.3 Content Validation

The backend reads the exact uploaded S3 object version and checks file signatures.

The current PDF validation checks the expected PDF header at the beginning of the file.

This is file-type validation, not a complete PDF structural inspection or malware scan.

Malware scanning and deeper document-content validation remain separate security capabilities rather than assumed existing controls.

### 9.4 Download Workflow

Document downloads require authenticated backend authorization.

The backend validates:

- Tenant membership.
- Submission authorization.
- Document identity.
- Object-key consistency.
- Document upload status.
- Stored S3 version identifier.
- Workflow state and role requirements.

The resulting presigned download URL is short-lived and references the validated object version.

## 10. Document Lifecycle Automation

The application uses scheduled Lambda workers for document lifecycle management.

### 10.1 Stage A — Pending Document Expiry

The document-expiry worker processes expired pending-upload records.

It validates candidate identity and expiry data and uses conditional transactional updates to protect submission state and counters.

### 10.2 Stage B — Document Cleanup

The document-cleanup worker removes expired document object versions and delete markers where cleanup is authorized.

It verifies that the expected object key has been cleared before completing the associated lifecycle transition.

### 10.3 Stage C — Document Finalization

The document-finalization worker verifies that the target S3 key contains no remaining versions or delete markers before finalizing the corresponding DynamoDB metadata cleanup.

It validates pagination markers and exact-key matches and fails closed when S3 verification is incomplete.

### 10.4 Stage D — Uploaded Document Version Hygiene

The document-version-hygiene worker removes unaccepted object versions while preserving the accepted document version.

It verifies that the accepted version is the only remaining version and that no delete markers remain before removing the corresponding DynamoDB hygiene index entry.

A maximum of 5,000 S3 versions per document is enforced. Exceeding this limit causes the worker to fail closed rather than proceeding with an incomplete cleanup.

### 10.5 Worker Execution Controls

The worker infrastructure uses scheduled execution, bounded Lambda timeouts, reserved concurrency, retry configurations, and dead-letter/failure destinations as configured in the respective Terraform resources.

Reserved concurrency is set to one for the reviewed lifecycle workers.

This limits overlapping execution of each individual worker function. It does not eliminate all possible operational failures or replace conditional database operations.

The worker configurations and code have been locally reviewed and tested. Successful execution against deployed AWS services has not been established.

## 11. Authentication and JWKS Synchronization

### 11.1 Cognito

The Cognito User Pool provides the application's authentication identity service.

The browser client uses Authorization Code flow without a client secret.

The configured API scope is:

`cloudsec-api/access`

Access and ID token validity are configured for 15 minutes, with a one-day refresh-token validity and refresh-token rotation.

The current callback and logout URLs use the local development frontend origin.

Production redirect URLs remain a deployment prerequisite.

### 11.2 JWKS Synchronization

A scheduled Lambda function synchronizes Cognito JSON Web Key Set information into a private S3 object.

The worker:

- Retrieves the public JWKS document over HTTPS.
- Uses certificate verification.
- Rejects redirects.
- Validates and canonicalizes key data.
- Publishes the validated document to the configured S3 object.
- Emits a CloudWatch success heartbeat.

The backend uses a bounded JWKS cache and validates signing keys before accepting access tokens.

The worker runs outside the VPC to avoid requiring additional NAT or VPC networking for its public Cognito JWKS retrieval.

### 11.3 Failure Handling

The synchronization configuration includes:

- EventBridge Scheduler.
- Lambda asynchronous retry settings.
- Failure SQS destination.
- Scheduler dead-letter queue.
- CloudWatch alarms for Lambda errors, queue messages, and stale success heartbeat.

These are configured monitoring and recovery mechanisms. Successful live notification delivery remains unverified.

## 12. Compute, Containers, and Deployment Integrity

### 12.1 EC2 Application Tier

The application runs on EC2 instances in the private subnets.

The Auto Scaling Group has:

- Minimum capacity conditional on the configured image digest.
- Desired capacity conditional on the configured image digest.
- Maximum capacity of two instances.
- Instances distributed across the two private subnets.

When no application image digest is configured, minimum and desired capacity are zero.

When a digest is configured, minimum and desired capacity are one.

This configuration does not guarantee high availability.

### 12.2 EC2 Security

The launch template configures:

- Amazon Linux 2023.
- IMDSv2 required.
- Metadata hop limit of one.
- Encrypted gp3 root EBS volume.
- No public IP.
- Application security-group restrictions.
- Systems Manager instance profile.

### 12.3 Container Security

The application container is configured to run with:

- Non-root UID/GID `10001`.
- Read-only root filesystem.
- Dropped Linux capabilities.
- `no-new-privileges`.
- Restricted PID count.
- Bounded memory.
- Bounded Docker log files.
- A dedicated temporary filesystem.

The application image is pulled using an immutable image digest.

### 12.4 ECR

The private ECR repository is configured with:

- Immutable image tags.
- Scan on push.
- KMS encryption.
- Lifecycle cleanup of untagged images.
- Retention of the ten most recent tagged images.

Scan on push is configured; enhanced scanning is not assumed.

### 12.5 Lambda Code Signing

AWS Signer is configured with an AWS Lambda signing profile.

The Lambda Code Signing Config allows the configured signing profile version and enforces trusted-artifact deployment.

The five Lambda packages are defined as signed artifacts.

This is an infrastructure-level deployment-integrity control. Successful signing-job execution and deployment enforcement have not been validated in a live AWS account.

## 13. Audit Logging, Monitoring, and Security Alerts

### 13.1 CloudTrail

The account-level CloudTrail trail is configured as:

`cloudsec-account-audit-trail`

It includes:

- Multi-region coverage.
- Global service events.
- Read and write management events.
- Log-file validation.
- S3 audit-log delivery.
- CloudWatch Logs delivery.
- SNS delivery notifications.

No data-event selectors are configured in the reviewed trail.

Therefore, S3 object-level data events should not be assumed to be captured by this trail.

### 13.2 CloudTrail Storage

CloudTrail audit records are delivered to a dedicated S3 bucket with:

- Block Public Access.
- Bucket-owner-enforced ownership.
- Versioning.
- Customer-managed KMS encryption.
- TLS enforcement.
- 365-day current and noncurrent version lifecycle expiration.
- S3 server-access logging.

CloudTrail log-file validation is enabled.

S3 versioning and CloudTrail log-file validation are useful integrity controls, but they do not independently make the bucket immutable.

### 13.3 CloudWatch

CloudTrail events are forwarded to a dedicated CloudWatch Logs group with:

- Customer-managed KMS encryption.
- 365-day retention.
- Restricted CloudTrail delivery role permissions.

CloudTrail metric filters and alarms cover:

1. Root account usage.
2. Failed console sign-ins.
3. Unauthorized API calls.
4. IAM policy changes.
5. IAM identity and credential changes.
6. Security group changes.
7. CloudTrail configuration tampering.

### 13.4 SNS Notifications

Two separate SNS topics are configured:

- CloudTrail delivery notifications.
- Cloud security alerts.

Both use KMS encryption.

Optional email subscriptions are controlled by Terraform variables.

Configured SNS policies restrict publishing to the relevant AWS service principals and expected source conditions.

### 13.5 Application and Network Logging

Additional telemetry includes:

- API Gateway access logs.
- AWS WAF logs.
- Application logs.
- ALB access logs.
- VPC Flow Logs.
- S3 server-access logs.

VPC Flow Logs capture all traffic types.

The WAF logging configuration explicitly redacts the Authorization header. No broader redaction claim is made.

S3 server-access logging is best-effort logging and should not be treated as a guaranteed real-time audit stream.

## 14. Frontend Architecture and Security

### 14.1 Frontend Stack

The frontend uses:

- React.
- TypeScript.
- Vite.
- React Router.
- AWS Amplify.
- Axios.
- TanStack Query.
- Vitest.
- Testing Library.
- Mock Service Worker.

### 14.2 Authentication Integration

The frontend uses Amplify for Cognito authentication.

The application uses the access token to authorize backend API requests.

The API client verifies that requests target the configured API origin and path before attaching the bearer token.

Direct S3 upload requests do not receive the Cognito bearer token.

### 14.3 Tenant Context

Tenant selection is maintained in browser session storage using a user-specific key.

Tenant selection is not treated as authorization evidence.

Backend membership and resource checks remain authoritative.

Query-cache keys include relevant user and tenant context. Authentication identity changes and sign-out clear cached application data.

### 14.4 Frontend Security Boundaries

The frontend provides role-aware navigation and controls, but backend authorization remains authoritative.

Application data is rendered as React text. No unsafe HTML-rendering sinks were identified during the reviewed frontend source inspection.

### 14.5 Frontend Hosting Limitation

A production frontend hosting layer has not yet been configured in Terraform or the reviewed deployment configuration.

Consequently, production delivery of the following response headers is still pending:

- Content-Security-Policy.
- Strict-Transport-Security.
- X-Content-Type-Options.
- Referrer-Policy.
- Permissions-Policy.

The production hosting design must also configure the correct HTTPS origin and Cognito callback/logout URLs.

These controls must be implemented at the actual frontend hosting or reverse-proxy layer. They are not established by the FastAPI backend container.

## 15. Availability and Operational Constraints

The architecture uses two Availability Zones for its public and private subnet layout and for the ALB and application Auto Scaling Group.

However:

- The ASG can scale to zero when no application image digest is configured.
- The ASG maximum capacity is two.
- Desired capacity is one when an image digest is configured.
- Interface VPC endpoints are currently configured only in private subnet A.
- There is no NAT Gateway.
- EC2 detailed monitoring is disabled.
- API Gateway X-Ray tracing is disabled.
- Internal ALB and target traffic currently use HTTP.

These are operational and deployment considerations, not proof of a deployed high-availability service.

The architecture intentionally avoids NAT Gateway costs, but private-instance bootstrap dependencies must be verified before deployment.

## 16. Security Validation and Testing

### 16.1 Backend

The backend test suite has reached:

**969 passed, 8 subtests passed.**

The reviewed areas include:

- Authentication and JWT validation.
- JWKS synchronization.
- Tenant authorization.
- Membership administration.
- Submission ownership.
- Workflow transitions.
- Document upload and download authorization.
- S3 storage validation.
- Document lifecycle workers.
- DynamoDB transaction behavior.

### 16.2 Frontend

The frontend test suite has reached:

**203 tests passed across 17 test files.**

ESLint and the TypeScript/Vite production build passed in the reviewed baseline.

Additional authentication regression coverage verifies that an authenticated user is cleared and cached data is removed when a refreshed token lacks the required API scope.

### 16.3 Terraform

The reviewed Terraform configuration passed:

- `terraform fmt` checks.
- `terraform validate`.
- Checkov infrastructure scanning.

Latest recorded Checkov result:

- 640 passed.
- 0 failed.
- 67 skipped.

The documented Checkov exceptions are maintained separately in:

`docs/security/checkov-exceptions.md`

### 16.4 Container Validation

The reviewed application container was tested locally with:

- Non-root execution.
- Read-only root filesystem.
- Dropped capabilities.
- No-new-privileges.
- Resource limits.
- Health endpoint checks.

These tests do not establish live AWS deployment behavior.

### 16.5 Validation Boundaries

The validation evidence is primarily local application testing, static infrastructure analysis, container testing, and local integration testing.

The following must not be claimed without further evidence:

- Successful Terraform deployment to AWS.
- Successful live Cognito authentication.
- Successful live API Gateway-to-ALB connectivity.
- Successful live S3 upload and download.
- Successful live KMS authorization.
- Successful CloudTrail delivery.
- Successful SNS email delivery.
- Successful live Lambda scheduled execution.
- Production availability or disaster recovery.

## 17. Outstanding Architecture and Deployment Requirements

The following items remain relevant before a production deployment:

| Priority | Item | Current status |
|---|---|---|
| High | Select and configure production frontend hosting | Pending |
| High | Configure production Cognito callback/logout URLs | Pending |
| High | Establish HTTPS for internal application hops | Pending |
| High | Validate EC2 bootstrap and private dependency access | Pending |
| High | Validate WAF rate-limit URI coverage against actual API routing | Pending |
| Medium | Review CloudTrail KMS permissions for SNS integration scoping | Review required |
| Medium | Evaluate CloudTrail data-event coverage requirements | Not configured |
| Medium | Evaluate frontend security headers and CSP | Hosting-dependent |
| Medium | Evaluate multi-AZ interface endpoint placement | Current deployment limitation |
| Medium | Evaluate stable API custom domain | Not configured |
| Medium | Evaluate X-Ray tracing and application instrumentation | Not configured |
| Medium | Validate monitoring and notification delivery | Not live-tested |
| Medium | Review audit-log immutability requirements | Not configured |
| Low | Evaluate signed pagination cursors | Optional hardening |
| Low | Evaluate malware scanning and deeper document-content validation | Not implemented |

The WAF rate-limit rule uses a URI scope-down condition beginning with `/api/api/v1/`. Its effective coverage must be verified against the actual API Gateway stage and path-forwarding behavior before treating the rule as proven API-wide rate limiting.

The CloudTrail KMS policy also contains a service permission for encrypted SNS integration that warrants a policy-scoping review. This is a review item, not a confirmed vulnerability.

## 18. Project Maturity

The project has progressed beyond an initial architecture proposal.

The following areas have substantial implementation and local validation evidence:

- Multi-tenant FastAPI backend.
- Cognito authentication and JWT validation.
- Tenant-scoped authorization.
- Transaction-protected membership and workflow operations.
- Secure document upload and download flows.
- DynamoDB data model and conditional operations.
- S3 object version hygiene and lifecycle workers.
- Private VPC architecture and security groups.
- API Gateway, VPC Link, internal ALB, and EC2 configuration.
- IAM least-privilege policies.
- KMS encryption configuration.
- CloudTrail and CloudWatch security monitoring configuration.
- Lambda code-signing configuration.
- Container hardening.
- React and TypeScript frontend.
- Automated backend and frontend tests.
- Terraform validation and Checkov scanning.

The project is **implemented and locally validated in substantial part, but not deployed or live-validated in AWS**.

Production hosting, internal transport encryption, deployment verification, operational monitoring validation, and other outstanding requirements must be completed before making production-readiness claims.

---

**Document maintenance:** Update this specification when application architecture, Terraform resources, security controls, or deployment assumptions materially change.