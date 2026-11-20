# Cloud Security Platform — Frontend

A React and TypeScript frontend for a secure, multi-tenant document submission and review platform. The application integrates with Amazon Cognito for authentication and a FastAPI backend for tenant-scoped workflows, document management, and audit visibility.

The frontend is designed around three application roles: Submitter, Reviewer, and Tenant Admin.

> **Implementation status:** The frontend application, authentication integration, API client, role-aware workflows, and automated tests are implemented. Production hosting, deployed Cognito configuration, and live AWS integration validation remain pending.

---

## 1. Technology Stack

| Component | Technology |
|---|---|
| UI framework | React 19 |
| Language | TypeScript |
| Build tool and development server | Vite |
| Routing | React Router |
| Styling | Tailwind CSS |
| Authentication | AWS Amplify Auth |
| Identity provider | Amazon Cognito |
| HTTP client | Axios |
| Server-state management | TanStack Query |
| Icons | Lucide React |
| Unit and component testing | Vitest |
| DOM testing | Testing Library |
| API mocking | Mock Service Worker |
| Test environment | jsdom |
| Code quality | ESLint |

---

## 2. Application Capabilities

The frontend provides the following application workflows:

- User authentication through Amazon Cognito.
- Authentication callback handling.
- Protected application routes.
- Tenant-aware application access.
- Role-aware dashboard and navigation.
- Submission creation and listing.
- Submission detail and workflow views.
- Document upload through presigned S3 POST requests.
- Document upload completion through the backend.
- Authorized document downloads.
- Tenant membership management.
- Tenant-scoped audit event visibility.

The backend remains authoritative for authentication, authorization, tenant isolation, document access, and workflow enforcement.

---

## 3. Application Roles

The application supports three roles.

| Role | Frontend capabilities |
|---|---|
| `SUBMITTER` | Create submissions, upload supported documents, and view authorized submissions. |
| `REVIEWER` | Access tenant-scoped submissions, review documents in permitted workflow states, and perform authorized workflow transitions. |
| `TENANT_ADMIN` | Manage tenant membership and view tenant-scoped audit events. |

### Authorization boundaries

- A user must have an authenticated and authorized tenant membership.
- Tenant selection does not grant access to another tenant.
- Submitters are restricted to their own submissions.
- Reviewers operate within their authorized tenant.
- Tenant administrators do not automatically receive document-content access.
- Users cannot grant themselves additional roles through frontend controls.

Frontend route protection and conditional UI rendering improve the user experience. They are not security boundaries by themselves. The backend independently enforces authorization.

---

## 4. Project Structure

The frontend source is organized by application responsibility.

```text
frontend/
├── public/
│   ├── favicon.svg
│   └── icons.svg
├── src/
│   ├── app/
│   │   ├── ProtectedRoute.tsx
│   │   └── TenantProtectedLayout.tsx
│   ├── features/
│   │   ├── audit/
│   │   ├── auth/
│   │   ├── submissions/
│   │   └── tenants/
│   ├── lib/
│   │   ├── amplify.ts
│   │   ├── api.ts
│   │   ├── apiServices.ts
│   │   └── queryClient.ts
│   ├── pages/
│   ├── test/
│   ├── types/
│   ├── App.tsx
│   ├── App.css
│   ├── index.css
│   └── main.tsx
├── .env.example
├── package.json
├── package-lock.json
├── eslint.config.js
├── vite.config.ts
├── vitest.config.ts
└── README.md
```

### Important directories

| Directory | Responsibility |
|---|---|
| `app/` | Protected routes and tenant-protected application layout. |
| `features/auth/` | Authentication state, session handling, and auth context. |
| `features/submissions/` | Submission-related UI and workflows. |
| `features/tenants/` | Tenant selection and membership management. |
| `features/audit/` | Tenant audit event interface. |
| `lib/` | Amplify configuration, API client, API services, and query client. |
| `pages/` | Application route pages. |
| `test/` | Shared test setup and utilities. |
| `types/` | Shared TypeScript types. |

---

## 5. Local Development Setup

### Prerequisites

- Node.js 22 or a compatible supported Node.js release.
- npm.
- Git.
- Access to the project repository.

### Install dependencies

From the repository root:

```bash
cd frontend
npm ci
```

`npm ci` installs dependencies from the committed lockfile.

### Configure environment variables

Create a local environment file:

```bash
cp .env.example .env.local
```

Edit `frontend/.env.local`:

```dotenv
# Amazon Cognito public browser configuration
VITE_COGNITO_USER_POOL_ID=
VITE_COGNITO_CLIENT_ID=
VITE_COGNITO_DOMAIN=

# Backend API base URL, including /api/v1
VITE_API_BASE_URL=
```

### Environment variable reference

| Variable | Purpose |
|---|---|
| `VITE_COGNITO_USER_POOL_ID` | Cognito User Pool identifier. |
| `VITE_COGNITO_CLIENT_ID` | Public browser application client identifier. |
| `VITE_COGNITO_DOMAIN` | Cognito hosted authentication domain. |
| `VITE_API_BASE_URL` | Backend API base URL, including the API prefix. |

The Cognito configuration must correspond to the browser client configured for the application.

`VITE_API_BASE_URL` should point to the backend API base path expected by the application. If omitted, the API client defaults to:

```text
/api/v1
```

This default assumes the frontend origin or its development proxy provides the corresponding API route. The current Vite configuration does not define a development proxy.

**Configuration notes:**

- Vite exposes `VITE_` variables to browser-side code.
- Never place AWS secret access keys, client secrets, private keys, or other confidential credentials in frontend environment variables.
- Cognito User Pool IDs and public browser client IDs are configuration identifiers, not secrets.
- Do not commit `.env.local` or other environment-specific files.

### Start the development server

```bash
npm run dev
```

Vite starts the local development server. Use the address printed in the terminal, normally:

```text
http://localhost:5173
```

The Cognito callback URL must match the browser application's configured callback URL.

---

## 6. Authentication Architecture

Authentication is implemented using AWS Amplify Auth and Amazon Cognito.

### Authentication flow

1. The user opens the frontend.
2. The authentication provider checks the current authentication state.
3. Unauthenticated users are directed to the login workflow.
4. Cognito handles authentication through its hosted sign-in experience.
5. Cognito redirects the browser to `/auth/callback`.
6. Amplify processes the authorization response.
7. The frontend obtains the authenticated session.
8. Protected routes become available after authentication and application-level checks.

### Cognito configuration

The frontend uses:

- A public Cognito browser application client.
- Authorization Code OAuth flow.
- Cognito as the configured identity provider.
- `openid`, `email`, and `cloudsec-api/access` scopes.
- A callback URL based on the current frontend origin.
- A sign-out redirect to the frontend root.

The frontend does not contain a Cognito client secret.

### API access token validation

Before sending an API request, the Axios request interceptor:

1. Resolves the configured API origin and base path.
2. Rejects requests outside the configured API origin or path.
3. Retrieves the current Cognito session.
4. Requires an access token.
5. Checks for the `cloudsec-api/access` scope.
6. Adds the access token as a Bearer authorization header.

The backend independently validates the token and enforces authorization.

---

## 7. API Integration

The frontend uses Axios for backend communication.

The shared API client is implemented in:

```text
src/lib/api.ts
```

API service functions are organized in:

```text
src/lib/apiServices.ts
```

### API client behavior

| Control | Implementation |
|---|---|
| Default API base path | `/api/v1` |
| Request timeout | 15 seconds |
| Default response format | JSON |
| Authentication | Cognito access token |
| Required API scope | `cloudsec-api/access` |
| API origin restriction | Enforced by request interceptor |
| API path restriction | Enforced by request interceptor |

API service functions encode dynamic path segments before constructing requests.

The frontend uses TanStack Query for server-state management, caching, and query invalidation.

The configured query client uses:

- 30-second stale time.
- Window-focus refetching.
- One query retry.
- No automatic mutation retries.
- In-memory query caching without persistent storage.

---

## 8. Document Upload and Download

Document handling uses the backend authorization workflow and Amazon S3 presigned requests.

### Supported document formats

| Format | MIME type |
|---|---|
| PDF | `application/pdf` |
| JPEG | `image/jpeg` |
| PNG | `image/png` |

Maximum supported document size:

```text
10 MiB
```

### Upload workflow

1. The frontend checks the selected file's MIME type and size.
2. The authenticated user requests an upload reservation through the backend.
3. The backend authorizes the operation and generates an S3 presigned POST request.
4. The browser uploads the file directly to S3.
5. The frontend calls the backend upload-completion endpoint.
6. The backend validates the uploaded object and finalizes the document record.

The direct S3 upload uses the presigned request and does not attach the Cognito Bearer token to the S3 request.

### Download workflow

1. The user requests a document download.
2. The backend verifies tenant membership, ownership or reviewer authorization, document state, and object-version information.
3. The backend returns an authorized presigned download URL.
4. The browser opens the document download target.

The backend remains responsible for deciding whether a document can be downloaded.

---

## 9. Frontend Security Controls

The frontend implements several security-related controls.

### Authentication and session handling

- Cognito-based authentication.
- Access-token requirement for API requests.
- Required API scope verification.
- Authentication state management.
- Session refresh handling.
- Query-cache clearing when authentication identity changes or the session becomes invalid.

### API request protection

- Configured API origin validation.
- Configured API base-path validation.
- Bearer token attachment only after session and scope checks.
- Request timeout.
- Encoded dynamic API path segments.

### Tenant and role handling

- Protected application routes.
- Tenant-protected application layout.
- User-specific tenant selection state.
- Tenant-aware query keys.
- Role-aware UI workflows.
- Cache isolation across authentication identity changes.

### Browser behavior

- Document downloads use `noopener` and `noreferrer`.
- React renders application data through normal text rendering.
- The reviewed frontend does not use unsafe HTML insertion APIs such as `dangerouslySetInnerHTML`.

### Important security limitations

Frontend controls do not replace backend enforcement.

The browser is an untrusted execution environment. Users can modify client-side state, requests, and UI behavior. All security-sensitive decisions must be independently enforced by the backend and AWS services.

The current implementation also relies on the browser's Amplify token storage behavior. Production deployment must account for the security implications of browser-side token storage and XSS exposure.

---

## 10. Testing

The frontend uses Vitest, Testing Library, jsdom, and Mock Service Worker.

### Run tests in watch mode

```bash
npm test
```

### Run the complete test suite once

```bash
npm run test:run
```

### Run ESLint

```bash
npm run lint
```

### Run the production build

```bash
npm run build
```

The build command performs TypeScript project compilation followed by the Vite production build.

### Test coverage areas

The implemented tests include:

- Authentication state transitions.
- Missing or invalid authentication scopes.
- Session refresh behavior.
- Authentication identity changes.
- Logout handling.
- Protected UI behavior.
- Tenant context behavior.
- Membership management interactions.
- Submission creation workflows.
- Tenant audit interface behavior.

Backend authorization and tenant-isolation tests are maintained separately in the backend test suite.

---

## 11. Production Build

Generate a production build:

```bash
npm run build
```

Vite writes the generated frontend assets to:

```text
dist/
```

To preview the generated build locally:

```bash
npm run preview
```

The preview server is intended for local inspection. It is not a production hosting solution.

### Production deployment requirements

Before exposing the frontend publicly, deployment must provide:

- HTTPS.
- Correct production Cognito callback and sign-out URLs.
- Correct production API base URL.
- Appropriate frontend security response headers.
- A Content Security Policy compatible with Cognito and the backend API.
- HSTS when the application is served exclusively over HTTPS.
- `X-Content-Type-Options`.
- An appropriate `Referrer-Policy`.
- A restrictive `frame-ancestors` policy.
- An appropriate `Permissions-Policy`.
- SPA route fallback configuration for React Router.
- A controlled frontend origin and corresponding backend CORS configuration.

These controls must be configured at the actual frontend hosting or reverse-proxy layer. They should not be assumed to exist merely because the React application builds successfully.

---

## 12. Current Deployment Status

The frontend is part of the larger AWS Cloud Security Platform project.

The current repository includes the frontend application and its integration code. However, the following remain deployment activities rather than completed live infrastructure:

- Production frontend hosting.
- Production Cognito callback and logout configuration.
- Production frontend security headers.
- Live Cognito authentication validation.
- Live API integration validation.
- End-to-end testing against deployed AWS infrastructure.

The backend and Terraform infrastructure are maintained separately in the repository.

No live AWS deployment or production frontend hosting should be inferred from a successful local frontend build.

---

## 13. Development Commands Reference

Run these commands from the `frontend/` directory.

| Command | Purpose |
|---|---|
| `npm ci` | Install locked dependencies. |
| `npm run dev` | Start the Vite development server. |
| `npm test` | Run Vitest in watch mode. |
| `npm run test:run` | Run tests once. |
| `npm run lint` | Run ESLint. |
| `npm run build` | Type-check and generate production assets. |
| `npm run preview` | Preview the production build locally. |

---

## 14. Related Project Documentation

For the broader application and security architecture, refer to:

- `../docs/architecture/application-architecture.md`
- `../docs/threat-model/application-threat-model.md`
- `../docs/security/frontend-security-review.md`
- `../docs/security/security-review-overview.md`
- `../docs/security/security-controls-matrix.md`
- `../docs/security/security-hardening-register.md`
- `../docs/architecture/aws-network-architecture.md`
- `../docs/architecture/iac-security-pipeline.md`

---

## 15. Project Objective

The frontend is designed to provide a usable interface for a security-focused, multi-tenant document workflow platform.

Its security model follows a fundamental principle:

**The frontend controls presentation and user experience; the backend and AWS infrastructure enforce security boundaries.**

Authentication, tenant isolation, document authorization, workflow enforcement, and auditability must remain enforceable independently of browser-side behavior.
