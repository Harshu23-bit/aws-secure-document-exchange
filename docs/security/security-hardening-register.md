# Security Hardening Register

**Project:** AWS Secure Infrastructure Blueprint  
**Document:** Security Hardening Register  
**Version:** 1.0  
**Review date:** 20 November 2026  
**Status:** Initial register established; remediation and AWS deployment validation pending.

---

## 1. Purpose

This register tracks security improvements, deployment prerequisites, validation gaps, and operational hardening activities identified during the project security review.

Its purpose is to:

- Convert review observations into actionable work items.
- Assign a priority based on security impact and deployment dependency.
- Define implementation and validation requirements.
- Establish measurable completion criteria.
- Prevent configuration assumptions from being mistaken for verified security outcomes.

This register is a project tracking document. It does not represent a list of confirmed vulnerabilities.

## 2. Scope

The register covers:

1. AWS deployment readiness.
2. Frontend production security.
3. Network and transport security.
4. API and application hardening.
5. Audit and monitoring coverage.
6. Document security.
7. CI/CD and software supply-chain security.
8. Operational resilience.
9. Defense-in-depth improvements.

The register is based on the reviewed application code, Terraform configuration, tests, and security documentation as of the review date.

## 3. Priority and Status Definitions

### 3.1 Priority

| Priority | Meaning |
|---|---|
| P0 — Deployment gate | Must be addressed or explicitly accepted before the relevant production deployment or exposure. |
| P1 — High | Significant security or deployment-readiness improvement; should be completed before production use. |
| P2 — Medium | Important hardening or operational improvement; schedule before or shortly after initial controlled deployment, depending on risk. |
| P3 — Low | Defense-in-depth or observability improvement that can be scheduled after higher-priority work. |

Priority describes remediation urgency, not proof of exploitability.

### 3.2 Status

| Status | Meaning |
|---|---|
| Open | Identified and not yet completed. |
| In progress | Implementation or validation has started. |
| Implemented — pending validation | Configuration or code has been changed, but acceptance evidence is incomplete. |
| Completed | Acceptance criteria have been met and evidence recorded. |
| Accepted risk | The project owner has explicitly accepted the residual risk. |
| Deferred | Intentionally postponed with a recorded reason and review point. |

All items initially remain **Open** unless evidence demonstrates otherwise.

## 4. Deployment Readiness

### HR-001 — Controlled AWS Deployment and Live Security Validation

**Priority:** P0 — Deployment gate  
**Category:** Deployment readiness  
**Classification:** Validation limitation, not a confirmed vulnerability  
**Status:** Open

**Observation**

The Terraform configuration and application have undergone local validation, but no AWS infrastructure has been deployed. The Terraform state currently contains zero managed resources.

Local validation does not prove that AWS service integrations, IAM permissions, network rules, or runtime behavior operate as intended.

**Required actions**

1. Review the final Terraform plan.
2. Confirm the expected AWS account, region, and assumed role.
3. Review estimated service costs and the deployment budget.
4. Deploy only after explicit authorization.
5. Inspect deployed security groups, IAM policies, S3 settings, KMS policies, Cognito configuration, and logging destinations.
6. Test API authentication and tenant authorization against deployed services.
7. Verify document upload, completion, download, and lifecycle processing.
8. Test CloudTrail delivery, alarms, and notification routing.
9. Record failures, deviations, and remediation evidence.

**Acceptance criteria**

- Deployed resources match the reviewed architecture.
- Critical security controls are verified against actual AWS resources.
- Application integration tests pass in the deployed environment.
- Logging and alert delivery are demonstrated.
- Any deviations are documented and assessed.
- Cost and cleanup procedures are verified.

**Dependencies**

- Final infrastructure review.
- Deployment authorization.
- AWS budget and cost controls.
- Required application artifacts.

**Evidence**

- Reviewed Terraform plan.
- Deployed resource configuration.
- AWS CLI inspection results.
- Application integration test results.
- Security validation report.

**Important:** Do not classify the infrastructure as production-ready solely because Terraform validation and Checkov pass.

### HR-002 — Production Frontend Hosting and Security Headers

**Priority:** P0 — Deployment gate  
**Category:** Frontend security  
**Classification:** Missing production deployment control  
**Status:** Open

**Observation**

The frontend currently has no established production hosting configuration in the reviewed Terraform or repository.

No production hosting layer has been configured to enforce browser security headers.

**Required actions**

1. Select and document the frontend hosting architecture.
2. Configure HTTPS and a production origin.
3. Implement a Content Security Policy appropriate to the actual application.
4. Configure `X-Content-Type-Options: nosniff`.
5. Configure an appropriate `Referrer-Policy`.
6. Configure `frame-ancestors` through CSP.
7. Evaluate and configure an appropriate `Permissions-Policy`.
8. Enable HSTS only after HTTPS is correctly established.
9. Verify headers on successful responses and relevant error responses.
10. Test authentication redirects and API communication under the final policy.

**Acceptance criteria**

- Frontend is served exclusively through the intended HTTPS origin.
- Required security headers are present.
- CSP permits only the required application, Cognito, and API resources.
- No unnecessary broad source expressions are introduced.
- Application authentication and normal workflows continue to function.
- Browser security-header inspection confirms the expected response.

**Dependencies**

- Hosting architecture selection.
- Production domain and certificate.
- Cognito callback and logout URL configuration.

**Evidence**

- Hosting configuration.
- Response-header inspection.
- CSP validation results.
- Browser authentication and workflow tests.

### HR-003 — Production Cognito and Application Origin Configuration

**Priority:** P0 — Deployment gate  
**Category:** Identity and frontend deployment  
**Classification:** Deployment dependency  
**Status:** Open

**Observation**

Current Cognito callback and logout URLs use localhost development origins.

Production identity configuration cannot be assumed to work until the actual frontend origin and redirect behavior are established.

**Required actions**

1. Establish the production frontend origin.
2. Configure exact Cognito callback URLs.
3. Configure exact logout URLs.
4. Verify the browser client OAuth flow.
5. Verify API Gateway authorizer configuration and required scopes.
6. Confirm the backend accepts only the intended browser client.
7. Test login, callback, refresh, logout, and expired-session behavior.

**Acceptance criteria**

- No development-only callback URL is required for production.
- Redirect destinations are explicitly configured.
- Login and logout work using the production origin.
- API access tokens contain the expected issuer, client identity, token type, and scope.
- Invalid or expired tokens are rejected.

**Dependencies**

- HR-002.
- Production domain and HTTPS configuration.
- Cognito deployment.

**Evidence**

- Cognito client configuration.
- Authentication test results.
- API authorization test results.

## 5. Network and API Hardening

### HR-004 — Verify WAF URI Scope-Down Coverage

**Priority:** P1 — High  
**Category:** Network and API security  
**Classification:** Configuration validation  
**Status:** Open

**Observation**

The custom WAF rate-based rule uses a URI scope-down condition beginning with:

`/api/api/v1/`

The actual request URI observed by WAF depends on API Gateway stage and path forwarding behavior. The intended rule coverage must not be assumed.

**Required actions**

1. Inspect the deployed API Gateway stage and resource path configuration.
2. Determine the URI evaluated by WAF for representative API requests.
3. Test the configured rate-based rule against the actual request path.
4. Verify that intended API routes are covered.
5. Verify that unrelated paths are not unintentionally included.
6. Review rate-limit behavior and false-positive impact.

**Acceptance criteria**

- Intended API requests match the WAF scope-down condition.
- Unrelated routes do not unintentionally match.
- Rate-based blocking is demonstrated in a controlled test.
- WAF metrics and logs show the expected rule behavior.

**Dependencies**

- AWS deployment.
- API Gateway and WAF association.

**Evidence**

- Deployed WAF rule inspection.
- Controlled request tests.
- WAF logs and metrics.

### HR-005 — Evaluate Internal Transport Encryption

**Priority:** P1 — High  
**Category:** Network security  
**Classification:** Transport hardening  
**Status:** Open

**Observation**

The configured internal request path uses HTTP between the VPC Link, internal ALB, and application target.

This is not public exposure, but it leaves internal transport without TLS protection.

**Required actions**

1. Evaluate supported TLS configurations for the VPC Link and ALB integration.
2. Determine whether HTTPS target-group communication is suitable for the application.
3. Identify certificate issuance, trust, renewal, and validation requirements.
4. Evaluate operational complexity and failure modes.
5. Update architecture and Terraform only after selecting a supported design.
6. Validate end-to-end request behavior.

**Acceptance criteria**

- The internal transport security design is documented.
- TLS is enabled where supported and justified.
- Certificate validation and renewal are operationally addressed.
- Backend connectivity and health checks succeed.
- Any remaining unencrypted internal segment is explicitly documented and risk-assessed.

**Dependencies**

- Deployed architecture.
- Certificate management design.
- API Gateway and ALB integration validation.

**Evidence**

- Updated architecture.
- Listener and target-group configuration.
- Certificate configuration.
- Controlled connectivity tests.

### HR-006 — Restrict Production API Documentation

**Priority:** P1 — High  
**Category:** Application security  
**Classification:** Application hardening  
**Status:** Open

**Observation**

FastAPI `/docs` and `/redoc` are currently enabled unconditionally in the reviewed application entry point.

Interactive API documentation is useful during development but should be deliberately controlled in production.

**Required actions**

1. Introduce an explicit environment-dependent documentation policy.
2. Disable interactive documentation in production unless there is a documented operational requirement.
3. Consider restricting OpenAPI schema access as well.
4. Ensure the setting cannot be accidentally enabled through an unsafe default.
5. Add tests for development and production behavior.

**Acceptance criteria**

- Production configuration disables or appropriately restricts `/docs`.
- Production configuration disables or appropriately restricts `/redoc`.
- OpenAPI schema exposure follows the same documented policy.
- Automated tests verify the expected behavior.

**Dependencies**

- Application configuration.
- Environment-specific deployment settings.

**Evidence**

- Updated application configuration.
- Automated tests.
- Deployed endpoint inspection.

### HR-007 — Evaluate API Distributed Tracing

**Priority:** P3 — Low  
**Category:** Observability  
**Classification:** Observability improvement  
**Status:** Open

**Observation**

API Gateway X-Ray tracing is disabled, and distributed tracing has not been established across the application request path.

**Required actions**

1. Determine whether distributed tracing is required for operational troubleshooting.
2. Evaluate API Gateway and application instrumentation.
3. Define sampling and retention expectations.
4. Ensure sensitive document data, credentials, and authorization headers are not recorded.
5. Validate trace correlation across relevant components.

**Acceptance criteria**

- A documented tracing decision exists.
- If enabled, traces correlate relevant request components.
- Sensitive data is excluded.
- Sampling and retention are appropriate.

**Dependencies**

- Deployment architecture.
- Logging and data-minimization policy.

**Evidence**

- Tracing configuration.
- Controlled trace inspection.
- Sensitive-data review.

## 6. Audit and Monitoring Hardening

### HR-008 — Evaluate CloudTrail S3 Data Events

**Priority:** P2 — Medium  
**Category:** Audit and monitoring  
**Classification:** Audit coverage limitation  
**Status:** Open

**Observation**

The reviewed CloudTrail trail captures management read/write events and global service events. No S3 object-level data event selectors were observed.

Management events do not provide complete object-level visibility for application bucket activity.

**Required actions**

1. Determine which S3 buckets and object prefixes require data-event auditing.
2. Evaluate the security value and cost of enabling S3 data events.
3. Define whether read events, write events, or both are required.
4. Scope selectors to relevant resources.
5. Update Terraform if the requirement is approved.
6. Test event delivery and queryability.

**Acceptance criteria**

- Required object-level activities are recorded.
- Selectors cover the intended buckets and prefixes.
- Unnecessary event volume is avoided.
- Events can be retrieved from the configured audit destination.
- Cost implications are documented.

**Dependencies**

- AWS deployment.
- Audit requirements.
- CloudTrail cost assessment.

**Evidence**

- Approved event-selector design.
- Terraform configuration.
- Controlled S3 operation and corresponding CloudTrail event.

### HR-009 — Review CloudTrail SNS KMS Permissions

**Priority:** P2 — Medium  
**Category:** IAM and cryptographic security  
**Classification:** Policy-hardening review  
**Status:** Open

**Observation**

The reviewed `AllowCloudTrailToUseKMSForSNS` permission grants CloudTrail `GenerateDataKey*` and `Decrypt` without SourceArn or SourceAccount conditions.

This is a policy-scoping review item, not a confirmed vulnerability. Any modification must preserve the AWS service integration requirements.

**Required actions**

1. Review the complete KMS key policy.
2. Confirm the documented AWS service integration requirements.
3. Determine which encryption context and condition keys are supported.
4. Identify whether the permission can be restricted to the intended trail.
5. Test encrypted SNS delivery after any policy change.
6. Confirm that unrelated principals cannot obtain broader key access.

**Acceptance criteria**

- The policy is scoped as narrowly as supported.
- CloudTrail can still publish encrypted notifications.
- No unrelated principal receives unnecessary access.
- The final policy and validation evidence are documented.

**Dependencies**

- AWS service integration documentation.
- Deployed CloudTrail and SNS resources.

**Evidence**

- Reviewed KMS key policy.
- Permission analysis.
- Successful encrypted notification delivery test.

### HR-010 — Validate Operational Alert Delivery

**Priority:** P1 — High  
**Category:** Monitoring and incident response  
**Classification:** Operational validation  
**Status:** Open

**Observation**

CloudWatch metric filters, alarms, and SNS topics are configured in Terraform, but live alarm evaluation and notification delivery have not been demonstrated.

**Required actions**

1. Deploy the required logging and monitoring resources.
2. Generate controlled test events for selected detection rules.
3. Verify metric filter behavior.
4. Verify alarm state transitions.
5. Verify SNS delivery to the intended subscribers.
6. Record false positives and missing detection cases.
7. Document the operational response procedure.

**Acceptance criteria**

- Selected test events produce the expected metrics.
- Relevant alarms enter the expected state.
- Notifications reach the intended destination.
- Alarm recovery behavior is understood.
- Response ownership and escalation steps are documented.

**Dependencies**

- AWS deployment.
- CloudTrail delivery.
- CloudWatch and SNS configuration.

**Evidence**

- CloudWatch metrics.
- Alarm history.
- SNS delivery confirmation.
- Controlled detection test report.

## 7. Frontend Security Hardening

### HR-011 — Review Browser Token Storage Strategy

**Priority:** P2 — Medium  
**Category:** Frontend authentication  
**Classification:** Browser security hardening  
**Status:** Open

**Observation**

The current Amplify browser configuration uses the installed default local-storage-based token behavior.

Browser-accessible tokens can be read by successful same-origin script execution. No confirmed XSS vulnerability was identified during the reviewed source inspection, but local storage remains a relevant residual risk.

**Required actions**

1. Review the current Amplify token-storage behavior and exact token lifecycle.
2. Evaluate the security and operational implications of alternative storage approaches.
3. Consider whether a backend-for-frontend architecture is justified.
4. Evaluate session persistence, refresh behavior, logout, and multi-tab behavior.
5. Avoid introducing a storage change without regression testing.
6. Document the accepted residual risk if the current approach remains.

**Acceptance criteria**

- Token-storage behavior is explicitly documented.
- The selected strategy has a threat-model justification.
- Authentication, refresh, and logout tests pass.
- User and tenant cache-clearing behavior remains correct.
- The decision and residual risk are recorded.

**Dependencies**

- Frontend authentication architecture.
- Cognito integration tests.

**Evidence**

- Authentication architecture decision.
- Storage configuration.
- Security and regression test results.

### HR-012 — Establish Production Content Security Policy

**Priority:** P1 — High  
**Category:** Frontend browser security  
**Classification:** Missing production control  
**Status:** Open

**Observation**

A production CSP has not been configured because the frontend hosting layer is not yet established.

**Required actions**

1. Identify all required script, style, image, font, connection, and frame sources.
2. Include only the necessary application and Cognito origins.
3. Avoid broad wildcards and unnecessary `unsafe-eval`.
4. Avoid `unsafe-inline` where practical.
5. Evaluate nonce- or hash-based script authorization if required.
6. Test in report-only mode before enforcement where appropriate.
7. Review violations and remove unnecessary allowances.

**Acceptance criteria**

- CSP is served as an HTTP response header.
- Authentication and application workflows work under the policy.
- No unnecessary broad origin allowances remain.
- CSP violations are reviewed.
- Enforcement behavior is tested in the production-like environment.

**Dependencies**

- HR-002.
- Final Cognito and API origins.

**Evidence**

- CSP configuration.
- Browser console and report results.
- Production-like workflow tests.

### HR-013 — Establish Additional Browser Security Headers

**Priority:** P1 — High  
**Category:** Frontend browser security  
**Classification:** Missing production control  
**Status:** Open

**Observation**

The production frontend hosting layer has not been configured to provide a complete browser security-header policy.

**Required actions**

Configure and validate:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy`
- CSP `frame-ancestors`
- Appropriate `Permissions-Policy`
- HSTS after HTTPS is correctly established

**Acceptance criteria**

- Headers are present on relevant production responses.
- Values match the documented security policy.
- HTTPS and certificate behavior are verified before HSTS enforcement.
- No conflicting header values are introduced by upstream layers.

**Dependencies**

- HR-002.
- HR-012.

**Evidence**

- Response-header inspection.
- Browser security tests.
- Hosting configuration.

## 8. Document Security Hardening

### HR-014 — Evaluate Malware Scanning and Structural Validation

**Priority:** P1 — High  
**Category:** Document security  
**Classification:** Defense-in-depth improvement  
**Status:** Open

**Observation**

Current document validation checks file type, size, encryption metadata, and expected file signatures.

PDF validation checks the expected header signature. It does not establish structural integrity, benign content, or absence of malware.

**Required actions**

1. Define supported document threat scenarios.
2. Evaluate an isolated malware-scanning workflow.
3. Evaluate deeper PDF and image validation.
4. Determine whether uploads must remain quarantined until scanning completes.
5. Define failure, timeout, retry, and rescan behavior.
6. Ensure scanning cannot bypass tenant authorization or accepted-version controls.
7. Document the impact on the submission workflow.

**Acceptance criteria**

- A documented document-validation policy exists.
- Supported file formats have appropriate validation.
- Malicious test files are handled according to policy.
- Failed or incomplete scanning does not mark a document as safe.
- Accepted document-version behavior remains correct.
- Operational cost and processing latency are understood.

**Dependencies**

- Document lifecycle architecture.
- Storage workflow.
- Scanning technology selection.

**Evidence**

- Threat-model update.
- Scanning architecture.
- Test results using controlled test files.
- Workflow integration evidence.

### HR-015 — Define High-Volume Version Hygiene Operations

**Priority:** P2 — Medium  
**Category:** Storage lifecycle  
**Classification:** Operational hardening  
**Status:** Open

**Observation**

Stage D intentionally fails closed when a document exceeds the configured 5,000-version processing threshold.

This prevents unbounded processing but requires an operational procedure for exceptional cases.

**Required actions**

1. Define how threshold failures are detected.
2. Document how affected documents are identified.
3. Establish an authorized investigation and recovery process.
4. Preserve the accepted version during recovery.
5. Verify exact-key filtering and deletion behavior.
6. Define escalation and audit requirements.

**Acceptance criteria**

- Threshold failures produce an actionable operational signal.
- Recovery procedures do not delete the accepted version.
- Recovery actions are authorized and auditable.
- Processing can resume safely after remediation.

**Dependencies**

- Stage D deployment.
- Operational monitoring.
- Document recovery procedure.

**Evidence**

- Runbook.
- Controlled test scenario.
- Recovery and audit evidence.

## 9. CI/CD and Supply-Chain Hardening

### HR-016 — Complete Automated Security Gates

**Priority:** P1 — High  
**Category:** CI/CD  
**Classification:** Pipeline completeness  
**Status:** Open

**Observation**

Local testing and security tooling are available, but complete CI enforcement has not been established by the reviewed evidence.

**Required actions**

1. Review all GitHub Actions workflows.
2. Ensure backend tests execute in CI.
3. Ensure frontend tests, linting, and production build execute in CI.
4. Enforce Terraform formatting and validation.
5. Run Checkov against Terraform changes.
6. Add dependency vulnerability scanning.
7. Add secret scanning.
8. Add container vulnerability scanning.
9. Ensure failures block the relevant build or deployment stage.
10. Document the handling of accepted exceptions.

**Acceptance criteria**

- Required checks execute automatically on relevant changes.
- Security-gate failures produce unsuccessful workflow results.
- Exceptions are documented and reviewed.
- CI results are reproducible.
- No secret values are exposed in workflow logs.

**Dependencies**

- GitHub Actions workflow implementation.
- Dependency and scanning tool selection.

**Evidence**

- Workflow definitions.
- Successful CI execution.
- Controlled failing-check demonstration.
- Security scan reports.

### HR-017 — Establish Secure Deployment Identity and Approval Controls

**Priority:** P1 — High  
**Category:** CI/CD identity and deployment security  
**Classification:** Deployment control gap  
**Status:** Open

**Observation**

The complete production deployment identity and approval model has not been validated.

**Required actions**

1. Define the CI deployment identity.
2. Prefer short-lived credentials and supported federation mechanisms over static access keys.
3. Scope permissions to required deployment operations.
4. Separate build and deployment permissions where appropriate.
5. Protect production environments with approval controls.
6. Restrict who can modify deployment workflows.
7. Record deployment activity and failure handling.

**Acceptance criteria**

- CI does not require long-lived AWS access keys where federation is supported.
- Deployment permissions follow least privilege.
- Production deployment requires the documented approval process.
- Workflow changes are appropriately protected.
- Deployment activity is auditable.

**Dependencies**

- HR-016.
- AWS deployment architecture.
- GitHub environment configuration.

**Evidence**

- Deployment identity configuration.
- IAM trust and permission policies.
- Environment protection configuration.
- Controlled deployment test.

## 10. Network Resilience and Operational Dependencies

### HR-018 — Validate Private EC2 Bootstrap Connectivity

**Priority:** P1 — High  
**Category:** Network and compute operations  
**Classification:** Deployment dependency  
**Status:** Open

**Observation**

The architecture has no NAT Gateway and the private route table has no default internet route.

EC2 bootstrap installs Docker through package repositories. Package retrieval must be verified through the intended private connectivity design.

**Required actions**

1. Identify the package repositories required by bootstrap.
2. Determine whether the required repositories are reachable through existing endpoints or another approved private path.
3. Test package installation from a private instance.
4. Evaluate private package mirroring or prebuilt image alternatives if required.
5. Ensure the solution does not introduce unintended public exposure or unrestricted egress.

**Acceptance criteria**

- EC2 bootstrap can retrieve required packages through the approved design.
- No unintended public ingress is introduced.
- Bootstrap failure is visible and actionable.
- The approach and any cost implications are documented.

**Dependencies**

- AWS deployment.
- Private endpoint and package access design.

**Evidence**

- Bootstrap logs.
- Connectivity test results.
- Deployed route and endpoint inspection.

### HR-019 — Evaluate Interface Endpoint Availability Across Zones

**Priority:** P2 — Medium  
**Category:** Network resilience  
**Classification:** Resilience improvement  
**Status:** Open

**Observation**

The reviewed configuration places interface endpoints in one private subnet.

This is a resilience limitation rather than proof of an exploitable vulnerability.

**Required actions**

1. Identify which interface endpoints are required for application operation.
2. Evaluate endpoint placement across both Availability Zones.
3. Assess service availability during an Availability Zone impairment.
4. Compare endpoint costs against resilience requirements.
5. Update the architecture and Terraform if justified.

**Acceptance criteria**

- Endpoint availability requirements are documented.
- Required endpoints have an approved multi-AZ design or an explicitly accepted single-AZ limitation.
- Application dependencies remain reachable under the intended failure model.

**Dependencies**

- Deployment architecture.
- Availability and cost requirements.

**Evidence**

- Endpoint configuration.
- Resilience test or documented design decision.
- Cost assessment.

## 11. Defense-in-Depth Improvements

### HR-020 — Evaluate Pagination Cursor Signing

**Priority:** P3 — Low  
**Category:** API hardening  
**Classification:** Defense-in-depth  
**Status:** Open

**Observation**

Pagination cursors are unsigned, but their contents are validated and bound to tenant, user, role, and expected key structure.

No cross-tenant bypass was identified during the review.

**Required actions**

1. Assess whether cursor integrity provides meaningful additional protection.
2. If adopted, define a versioned cursor format.
3. Sign cursor contents using a suitable server-side mechanism.
4. Validate signature, expiry, tenant, user, and role.
5. Ensure signing-key rotation does not break valid pagination unexpectedly.

**Acceptance criteria**

- The decision is documented.
- If implemented, modified cursor contents are rejected.
- Existing tenant and user binding remains enforced.
- Pagination compatibility and key rotation are tested.

**Dependencies**

- API design.
- Key-management approach if signing is implemented.

**Evidence**

- Architecture decision.
- Cursor implementation and tests, if adopted.

### HR-021 — Review CloudTrail and Audit Retention Requirements

**Priority:** P2 — Medium  
**Category:** Audit and compliance readiness  
**Classification:** Governance and operational hardening  
**Status:** Open

**Observation**

The project has configured retention policies for several log destinations, but a consolidated retention and access policy has not been established as an operational standard.

**Required actions**

1. Define retention requirements for each log category.
2. Distinguish application audit events from infrastructure logs.
3. Identify access and deletion permissions.
4. Evaluate legal, privacy, and cost requirements.
5. Document restoration and investigation procedures.
6. Verify lifecycle behavior after deployment.

**Acceptance criteria**

- A retention policy exists for all relevant log categories.
- Access is restricted to authorized roles.
- Retention and lifecycle settings match the approved policy.
- Cost and deletion behavior are understood.

**Dependencies**

- Audit and operational requirements.
- AWS deployment.

**Evidence**

- Retention policy.
- Terraform configuration.
- Deployed lifecycle inspection.

## 12. Recommended Remediation Sequence

The following sequence groups work by dependency rather than suggesting that every item must be completed immediately.

| Sequence | Work items | Objective |
|---|---|---|
| 1 | HR-001 | Establish controlled deployment and live validation process. |
| 2 | HR-002, HR-012, HR-013 | Establish production frontend hosting and browser security controls. |
| 3 | HR-003 | Configure and validate production identity and redirect behavior. |
| 4 | HR-004, HR-005, HR-018 | Validate WAF coverage, internal transport, and private bootstrap connectivity. |
| 5 | HR-006, HR-010 | Harden API documentation and validate alert delivery. |
| 6 | HR-008, HR-009, HR-021 | Improve audit coverage, KMS policy scoping, and retention governance. |
| 7 | HR-014, HR-015 | Evaluate document scanning and exceptional version-hygiene operations. |
| 8 | HR-016, HR-017 | Complete CI security gates and secure deployment identity. |
| 9 | HR-011, HR-019 | Review browser token storage and network resilience. |
| 10 | HR-007, HR-020 | Evaluate distributed tracing and cursor signing. |

The order may change when implementation dependencies or newly discovered risks justify reprioritization.

## 13. Risk Acceptance Requirements

An item should only be marked **Accepted risk** when the decision includes:

- A clear description of the residual risk.
- The reason remediation is not currently being performed.
- The expected impact and likelihood.
- Any compensating controls.
- The person or role authorizing acceptance.
- A review date or trigger for reassessment.

A deferred item is not automatically an accepted risk.

Deployment prerequisites must not be silently waived merely because the corresponding Terraform resource exists.

## 14. Change and Evidence Management

For each item, maintain:

1. Item identifier.
2. Current status.
3. Implementation date.
4. Relevant source files or AWS resources.
5. Test or validation evidence.
6. Any remaining limitations.
7. Risk acceptance or deferral rationale, where applicable.

After a change:

- Re-run relevant unit and integration tests.
- Re-run Terraform formatting and validation for infrastructure changes.
- Re-run applicable Checkov checks.
- Review the relevant security documentation.
- Record actual AWS validation separately from local validation.

Do not mark an item completed based solely on code modification.

## 15. Current Assessment

At the time of this register's creation:

- No AWS infrastructure has been deployed.
- Local application and frontend validation has been performed.
- Terraform formatting and validation have passed.
- Checkov has recorded 640 passed, 0 failed, and 67 skipped checks.
- Backend authentication, tenant isolation, document workflows, and lifecycle workers have undergone source review and automated testing.
- Frontend authentication, tenant context, API communication, and browser security have undergone source review and automated testing.
- No confirmed exploitable backend or frontend vulnerability was identified in the reviewed components.
- Production frontend hosting, live AWS validation, and complete CI/CD security enforcement remain outstanding.

The open items in this register should be tracked through implementation and evidence collection. Their presence does not imply that each item is an exploitable vulnerability.

## 16. Conclusion

This register establishes a practical remediation and validation backlog for the AWS Secure Infrastructure Blueprint.

The immediate focus is to establish secure production deployment prerequisites, validate actual AWS enforcement, complete frontend hosting security, and demonstrate operational monitoring and CI/CD controls.

Further defense-in-depth improvements should be implemented according to their assessed value, operational cost, and impact on the architecture.

The register should be reviewed whenever the architecture changes, a new security finding is confirmed, or deployment validation reveals a discrepancy.
