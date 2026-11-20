# Frontend Security Review

**Project:** AWS Secure Infrastructure Blueprint  
**Document:** Frontend Security Review  
**Version:** 1.1  
**Review date:** 20 November 2026  
**Status:** Source-code review and local frontend validation completed; production hosting validation pending  
**Frontend Stack:** React, TypeScript, Vite  
**Authentication:** Amazon Cognito through AWS Amplify  
**Related Documents:**
- `docs/architecture/application-architecture.md`
- `docs/security/security-review-overview.md`
- `docs/threat-model/application-threat-model.md`

---

## 1. Executive Summary

This document records the security review of the React and TypeScript frontend for the Secure Multi-Tenant Document Exchange Platform.

The frontend provides authenticated workflows for Submitters, Reviewers, and Tenant Administrators. It integrates with Amazon Cognito through AWS Amplify and communicates with the FastAPI backend through authenticated API requests.

The review focused on:

- Authentication state management.
- Cognito access-token handling.
- API request authorization.
- Protected routes.
- Tenant selection and context.
- Query-cache isolation.
- Submission creation.
- Team-member management.
- Tenant audit views.
- Direct S3 document uploads.
- Document downloads.
- Client-side validation.
- Potential cross-site scripting risks.
- Production frontend security requirements.

The reviewed implementation contains several positive security controls:

- Authenticated API requests require a valid access token and expected API scope.
- API requests attach the access token as a Bearer token.
- Tenant context is maintained separately from authentication identity.
- Query keys include user and tenant context.
- Cached application data is cleared when the authenticated identity changes or signs out.
- Backend authorization remains authoritative.
- Direct S3 uploads use presigned authorization rather than exposing general AWS credentials.
- React renders application data as text.
- No identified unsafe HTML insertion operations were found in the reviewed source.

No confirmed exploitable frontend vulnerability or client-side tenant-isolation bypass was identified in the reviewed components.

However, the frontend does not yet have a production hosting configuration. Production HTTPS, Content Security Policy, security headers, callback URLs, and hosting-layer protections remain deployment requirements.

**Overall assessment:** The reviewed frontend has a sound security foundation, but production security depends on completing the hosting configuration and addressing the residual risks documented below.

## 2. Review Scope

### 2.1 Authentication

Reviewed:

- `frontend/src/features/auth/AuthProvider.tsx`
- `frontend/src/features/auth/authContext.ts`
- `frontend/src/features/auth/useAuth.ts`
- `frontend/src/lib/amplify.ts`
- `frontend/src/app/ProtectedRoute.tsx`
- `frontend/src/App.tsx`
- Authentication tests.

### 2.2 API Communication

Reviewed:

- `frontend/src/lib/api.ts`
- `frontend/src/lib/apiServices.ts`
- `frontend/src/lib/queryClient.ts`

### 2.3 Tenant Context

Reviewed:

- `frontend/src/features/tenants/TenantProvider.tsx`
- `frontend/src/features/tenants/tenantContext.ts`
- `frontend/src/features/tenants/useTenant.ts`
- `frontend/src/app/TenantProtectedLayout.tsx`
- Tenant-provider tests.

### 2.4 Application Features

Reviewed:

- `frontend/src/features/submissions/CreateSubmissionModal.tsx`
- `frontend/src/features/tenants/TeamMembersPanel.tsx`
- `frontend/src/features/audit/TenantAuditPanel.tsx`
- Related component tests.
- Submission and tenant-related pages and types.

### 2.5 Review Exclusions

This review does not establish:

- Production browser security-header enforcement.
- Production hosting security.
- Independent browser penetration testing.
- Production Cognito callback behavior.
- Live API Gateway and backend authorization.
- Live S3 upload-policy enforcement.
- A complete third-party dependency audit.
- A formal accessibility or privacy assessment.

## 3. Frontend Architecture and Trust Boundaries

### 3.1 Frontend Architecture

The frontend uses:

| Component | Responsibility |
|---|---|
| React | User interface and component rendering |
| TypeScript | Application type safety |
| Vite | Development server and production build |
| React Router | Client-side navigation |
| AWS Amplify | Cognito authentication integration |
| Axios | API and presigned S3 requests |
| TanStack Query | Server-state management and caching |
| Tailwind CSS | Styling |
| Vitest | Automated testing |
| Testing Library | Component testing |
| MSW | API mocking during tests |

### 3.2 Authentication Flow

```text
User
 |
 v
React Application
 |
 v
AWS Amplify
 |
 v
Amazon Cognito
 |
 | Authorization Code Flow
 v
Authentication Callback
 |
 v
AuthProvider
 |
 | Access Token and Scope Validation
 v
Authenticated Application
```

The frontend uses Cognito's public browser client without a client secret.

The configured browser authentication flow uses Authorization Code flow.

### 3.3 API Request Flow

```text
React Component
 |
 v
API Service
 |
 v
Axios API Client
 |
 v
Request Interceptor
 |
 | Obtain Cognito Session
 | Validate Access Token
 | Validate Required Scope
 | Attach Bearer Token
 v
API Gateway
 |
 v
FastAPI Backend
 |
 v
Backend Authorization
```

The frontend performs preliminary authentication checks, while the backend remains responsible for enforcing access control.

### 3.4 Document Upload Flow

```text
React Upload Component
 |
 | Validate file type and size
 v
Backend Upload Request
 |
 | Authenticated API Request
 v
FastAPI
 |
 | Authorize user and reserve upload
 v
Presigned S3 POST Response
 |
 v
Browser Direct Upload
 |
 v
Private S3 Bucket
 |
 v
Backend Upload Completion
 |
 v
Document Record Updated
```

The browser uses the presigned S3 authorization for the upload. It does not need to attach the Cognito Bearer token to the S3 upload request.

## 4. Authentication Security

### 4.1 Cognito Integration

The frontend uses AWS Amplify to integrate with Amazon Cognito.

The reviewed browser-client configuration uses:

- Public Cognito application client.
- No client secret.
- Authorization Code flow.
- Cognito as the identity provider.
- Configured callback and logout URLs for local development.
- Access-token and ID-token validity of 15 minutes.
- Refresh-token validity of one day.
- Refresh-token rotation with a configured grace period.

The frontend requests the application API scope:

`cloudsec-api/access`

The backend separately validates the token and required scope.

### 4.2 Authentication State Management

The authentication provider maintains explicit application states:

- `loading`
- `authenticated`
- `unauthenticated`
- `error`

This prevents the application from treating an unresolved authentication state as an authenticated session.

The provider handles:

- Session retrieval.
- Access-token validation.
- Required-scope validation.
- Authenticated-user identity.
- Authentication refresh.
- Logout.
- Authentication-related events.
- Query-cache cleanup.

### 4.3 Refresh Race Protection

The authentication provider uses an operation counter to prevent stale asynchronous refresh operations from overwriting newer authentication state.

This is important when:

- Multiple refresh operations overlap.
- A user logs out while a refresh is pending.
- The authenticated identity changes.
- A delayed refresh returns after a newer operation.

The reviewed implementation includes tests for stale refresh ordering and logout-related races.

### 4.4 Invalid Scope Handling

A regression test was added for the following scenario:

1. User A is authenticated.
2. The session is refreshed.
3. The refreshed access token lacks the required API scope.
4. The authentication provider transitions into an error state.
5. The authenticated user is cleared.
6. The query cache is cleared.

This prevents stale authenticated application state from remaining available after the required scope is lost.

### 4.5 Authentication Review Outcome

**Status:** Reviewed; no confirmed authentication-state bypass identified.

The frontend checks the access token and expected scope before making protected API requests.

These checks improve client behavior but do not replace backend token verification.

## 5. Token Storage and Browser Security

### 5.1 Token Storage

The reviewed Amplify configuration does not explicitly define a custom token-storage provider.

The installed Amplify browser implementation therefore uses its default browser token storage behavior, which is localStorage in this configuration.

This has an important security implication:

JavaScript executing in the application origin can access browser localStorage.

Consequently, successful same-origin JavaScript execution, including an XSS compromise, could expose stored authentication tokens.

### 5.2 Risk Assessment

| Risk | Assessment |
|---|---|
| Direct access to localStorage by application JavaScript | Expected browser behavior |
| Token exposure following successful XSS | Residual risk |
| Client-side token validation bypass | Backend independently validates tokens |
| Token persistence after logout | Logout and cache-clearing behavior reviewed; live Cognito behavior pending |
| Stolen unexpired access token | Potential temporary account impersonation |

The review did not establish a confirmed XSS vulnerability.

However, the token-storage model makes prevention of script injection particularly important.

### 5.3 Recommended Hardening

- Configure a restrictive Content Security Policy.
- Avoid unsafe HTML rendering.
- Avoid unnecessary third-party scripts.
- Keep frontend dependencies updated.
- Review token-storage alternatives before production deployment.
- Validate logout and token-revocation behavior against deployed Cognito resources.

Changing token storage should be treated as an authentication architecture decision rather than an isolated configuration change.

## 6. API Client Security

### 6.1 API Configuration

The API client uses:

- `VITE_API_BASE_URL` when configured.
- `/api/v1` as the default API base path.
- A 15-second request timeout.
- `Accept: application/json`.

### 6.2 Request Interceptor

Before sending an authenticated API request, the interceptor:

1. Validates the intended API target.
2. Obtains the current Cognito session.
3. Retrieves the access token.
4. Checks the required API scope.
5. Attaches the token using the Bearer authorization scheme.

Requests without a valid access token or required scope are not treated as authenticated API requests.

### 6.3 API Target Restrictions

The API client performs origin and path checks before attaching authentication credentials.

This reduces the risk of sending Cognito Bearer tokens to unintended request destinations.

API service functions also encode resource path segments when constructing tenant, submission, user, and document paths.

### 6.4 Backend Authorization

The frontend does not determine whether a user is authorized to access a protected resource.

The backend independently checks:

- JWT validity.
- User identity.
- Tenant membership.
- Membership status.
- Role permissions.
- Submission ownership.
- Workflow state.
- Document access conditions.

Client-side route protection and request checks are defense-in-depth controls, not security boundaries.

### 6.5 Review Outcome

**Status:** Reviewed; no confirmed token-forwarding or frontend authorization bypass identified in the reviewed API client.

Production API origin and path configuration still require validation.

## 7. Tenant Context and Client-Side Isolation

### 7.1 Tenant Selection

The frontend maintains selected tenant context through the tenant provider.

The selected tenant is stored using a user-specific sessionStorage key.

This storage is used for tenant-selection state, not as the authentication-token store.

### 7.2 Tenant Context Validation

The frontend accepts tenant selections only from the tenant identifiers available to the authenticated user.

The selected tenant is therefore constrained by the user's available tenant context.

However, frontend tenant selection is not an authorization mechanism.

The backend independently verifies membership and tenant access for protected operations.

### 7.3 Query-Key Isolation

The frontend query keys include relevant user and tenant context.

This reduces the risk of reusing cached data across different authenticated identities or selected tenants.

### 7.4 Cache Clearing

The reviewed authentication implementation clears application query-cache data when:

- The authenticated user changes.
- The user signs out.
- The authentication state becomes invalid under the reviewed failure paths.

This is important because cached data may otherwise remain visible after a user switches accounts.

### 7.5 Tenant Isolation Review Outcome

**Status:** Reviewed; no confirmed client-side tenant-cache isolation bypass identified.

Client-side isolation remains supplementary. The backend must continue enforcing tenant boundaries independently.

## 8. Protected Routes and Role-Based User Interfaces

### 8.1 Protected Routes

The frontend uses protected-route components to control navigation based on authentication state.

The tenant-protected layout also requires an appropriate tenant context before rendering tenant-specific application workflows.

These controls improve the user experience and prevent ordinary navigation into unavailable application areas.

They do not prevent a user from manually constructing HTTP requests.

### 8.2 Role-Aware Interfaces

The frontend displays functionality according to the authenticated user's role.

The reviewed application includes:

- Submitter workflows.
- Reviewer workflows.
- Tenant Administrator workflows.

### 8.3 Team Member Management

The team-management interface includes restrictions on operations involving:

- The current user.
- Tenant Administrators.
- Inactive members.
- Prohibited role transitions.

These checks reduce accidental or unauthorized actions through the interface.

The backend independently enforces membership-management authorization.

### 8.4 Tenant Audit Panel

The tenant audit panel:

- Restricts its interface to the intended administrative role.
- Uses tenant-scoped query keys.
- Supports cursor-based pagination.
- Retrieves audit information through backend API services.

The backend remains responsible for ensuring that audit events belong to the authorized tenant.

## 9. Document Upload Security

### 9.1 Client-Side File Validation

The upload component performs preliminary checks for:

- Supported file types.
- Maximum file size.

Supported formats:

- PDF.
- JPEG.
- PNG.

Maximum document size:

`10 MiB`

These checks provide immediate user feedback but are not trusted as authoritative validation.

### 9.2 Presigned Upload

The browser requests upload authorization from the backend.

The backend performs authorization and creates the upload reservation before returning presigned S3 POST information.

The browser then uploads directly to S3 using the returned presigned authorization.

The S3 upload request does not attach the Cognito Bearer token.

### 9.3 Upload Completion

After the upload, the frontend calls the backend completion endpoint.

The backend verifies the uploaded object, metadata, encryption, and exact S3 VersionId before accepting the document.

The frontend cannot independently mark a document as successfully accepted merely because the browser upload request completed.

### 9.4 Upload Security Assessment

The design reduces exposure by avoiding general-purpose AWS credentials in the browser.

The backend remains authoritative for:

- Tenant authorization.
- Submission ownership.
- Workflow state.
- Document identity.
- S3 object key.
- Encryption requirements.
- Uploaded object validation.

### 9.5 Residual Risks

- Presigned URLs are bearer authorizations until expiration.
- A valid upload URL may be replayed within its validity period.
- Client-side file validation can be bypassed.
- File signatures alone do not establish that a document is safe.
- Malware scanning is not currently established.

## 10. Document Download Security

The frontend requests document downloads through backend API services.

The backend performs authorization before issuing a short-lived presigned download URL.

The reviewed backend design binds downloads to the accepted S3 object version.

The frontend opens the resulting download target using a new browser context with:

`noopener noreferrer`

This prevents the opened document destination from obtaining access to the original window through the browser's opener relationship.

The frontend does not independently grant document access based on a user-supplied S3 URL.

**Review outcome:** The reviewed frontend download flow follows the backend-authoritative authorization model.

## 11. Cross-Site Scripting and DOM Security

### 11.1 Source Review

The reviewed source was examined for unsafe DOM operations.

The following patterns were not identified:

- `dangerouslySetInnerHTML`
- `innerHTML`
- `outerHTML`
- `insertAdjacentHTML`
- `document.write`
- `eval`
- `new Function`

React's normal text-rendering behavior escapes text content rather than interpreting it as HTML.

### 11.2 Assessment

No confirmed DOM-based XSS vulnerability was identified in the reviewed components.

However, this does not establish that the complete application is immune to XSS.

Potential future risks include:

- Unsafe HTML rendering introduced by new components.
- Insecure third-party dependencies.
- Unsafe Markdown or rich-text rendering.
- Script injection through compromised dependencies.
- Insecure hosting configuration.

### 11.3 Required Controls

- Maintain safe React rendering practices.
- Avoid unsafe HTML insertion.
- Review rich-text and Markdown rendering if introduced.
- Configure production CSP.
- Keep dependencies updated.
- Perform browser-based security testing after deployment.

## 12. Security Headers and Frontend Hosting

### 12.1 Current Hosting Status

The reviewed repository does not contain a production frontend hosting configuration.

No production hosting layer was identified for:

- CloudFront.
- S3 static website hosting.
- AWS Amplify Hosting.
- Vercel.
- Netlify.
- Nginx.
- Caddy.
- A dedicated frontend container.

The existing root Dockerfile is for the backend application.

Therefore, production frontend response headers cannot currently be verified.

### 12.2 Required Production Security Headers

The final hosting layer should implement the following controls.

| Header | Purpose |
|---|---|
| Content-Security-Policy | Restrict permitted script, style, image, and connection sources |
| Strict-Transport-Security | Enforce HTTPS after HTTPS is correctly configured |
| X-Content-Type-Options | Prevent MIME-type sniffing |
| Referrer-Policy | Limit unnecessary referrer information |
| Permissions-Policy | Restrict unnecessary browser capabilities |
| CSP `frame-ancestors` | Restrict framing and reduce clickjacking exposure |

### 12.3 Content Security Policy

The CSP must account for the actual application integrations.

Expected requirements include:

- Frontend origin.
- Cognito authentication endpoints.
- Backend API origin.
- Required asset sources.
- Any approved supporting services.

Avoid broad wildcard source expressions.

Avoid enabling `unsafe-eval`.

Do not add `unsafe-inline` without a documented requirement and an appropriate nonce- or hash-based alternative.

### 12.4 HTTPS and HSTS

Production frontend traffic must use HTTPS.

HSTS should be enabled only after HTTPS is correctly established and all relevant application endpoints support it.

The current localhost development callback configuration must not be treated as a production authentication configuration.

## 13. Client-Side State and Caching

### 13.1 Query Client

The reviewed TanStack Query configuration includes:

| Setting | Configuration |
|---|---|
| Stale time | 30 seconds |
| Refetch on window focus | Enabled |
| Query retry | 1 |
| Mutation retry | 0 |
| Persistent query storage | Not configured |

### 13.2 Security Benefits

- Server-state caching is kept in memory.
- Query keys include user and tenant context where applicable.
- Identity changes trigger cache cleanup.
- Mutations are not automatically retried.
- Window focus can refresh stale server data.

### 13.3 Residual Risks

In-memory cache is not a replacement for backend authorization.

Sensitive information already delivered to a browser may remain accessible to the current browser session until it is cleared or the application is closed.

Production testing should verify cache behavior during account switching, tenant switching, logout, and authentication failure.

## 14. Security Test Evidence

### 14.1 Frontend Baseline

The recorded frontend baseline includes:

| Validation | Result |
|---|---|
| Automated tests | 203 passed |
| Test files | 17 |
| ESLint | Passed |
| TypeScript build | Passed |
| Vite production build | Passed |

### 14.2 Authentication Tests

The reviewed authentication tests cover:

- No valid session.
- Missing access token.
- Missing required API scope.
- Session retrieval failure.
- Authenticated identity changes.
- Logout.
- Cognito Hub sign-out behavior.
- Redirect failure.
- Stale refresh ordering.
- Logout and refresh race handling.

A focused regression test verifies that a refreshed token missing the required scope causes the provider to clear authenticated user state and cached application data.

Recorded focused authentication result:

`12 tests passed`

### 14.3 Tenant and Component Tests

The reviewed test coverage includes:

- Tenant provider behavior.
- Team-member management restrictions.
- Tenant audit panel behavior.
- Submission creation.
- Authentication context behavior.
- Query-cache isolation behavior.

### 14.4 Validation Limitations

The latest recorded frontend test result is 203 passed across 17 test files. TypeScript compilation, ESLint, and the Vite production build also passed during local validation on 20 November 2026.

These results establish local automated behavior. They do not establish:

- Production Cognito behavior.
- Production browser security headers.
- Live API authorization.
- Live S3 upload enforcement.
- Production cross-origin behavior.
- Browser penetration-test results.

## 15. Frontend Findings and Hardening Register

The following items represent the current frontend security findings.

| ID | Finding | Classification | Priority |
|---|---|---|---|
| FE-01 | Browser token storage is JavaScript-accessible | Security hardening | Medium |
| FE-02 | Production CSP is not configured | Deployment hardening | High |
| FE-03 | Production security headers are not configured | Deployment hardening | High |
| FE-04 | Production frontend hosting is not configured | Deployment dependency | High |
| FE-05 | Production Cognito callback and logout URLs are pending | Deployment dependency | High |
| FE-06 | Backend authorization remains essential for every protected operation | Security requirement | High |
| FE-07 | Rich document content and malware scanning are not established | Document security hardening | Medium |
| FE-08 | Frontend dependency and browser security maintenance must continue | Ongoing maintenance | Medium |

No item above should automatically be interpreted as a confirmed exploitable vulnerability.

### 15.1 Recommended Remediation Order

**Before production deployment**

1. Select and configure frontend hosting.
2. Configure HTTPS.
3. Implement CSP.
4. Implement security headers.
5. Configure production Cognito callback and logout URLs.
6. Validate frontend-to-API origin and CORS behavior.
7. Test authentication refresh and logout in the deployed environment.

**Security hardening**

1. Evaluate token-storage alternatives.
2. Review all future rich-text and document-rendering functionality.
3. Establish dependency scanning and update procedures.
4. Evaluate document malware scanning.
5. Perform browser-based security testing.

## 16. Final Assessment

The reviewed frontend implements a reasonable security model for a multi-tenant application.

The strongest areas are:

- Explicit authentication states.
- Cognito access-token and scope validation.
- Authenticated API request handling.
- Tenant-aware application context.
- Query-cache isolation.
- Backend-authoritative authorization.
- Constrained direct S3 upload flow.
- Safe React text rendering.
- Automated authentication and component tests.

The principal remaining concerns are production hosting, browser security headers, token-storage exposure in the event of XSS, and production integration validation.

The frontend should be considered **source-reviewed and locally validated, with production deployment security still pending**.

---

**Review maintenance:** Reassess this document whenever authentication handling, API communication, tenant context, browser storage, document workflows, or frontend hosting changes materially.
