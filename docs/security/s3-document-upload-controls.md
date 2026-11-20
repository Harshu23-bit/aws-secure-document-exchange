# S3 Document Upload Security Controls

## Scope

This document describes the application-level and infrastructure-level
controls used for document uploads and downloads.

The application uses presigned S3 POST requests for uploads and
version-specific presigned GET requests for downloads.

## Upload authorization

Before issuing an upload request, the API:

1. Authenticates the caller through Cognito.
2. Resolves the caller's tenant membership.
3. Requires the SUBMITTER role.
4. Verifies that the caller owns the submission.
5. Requires the submission to be in DRAFT state.
6. Generates the document ID and S3 object key server-side.
7. Creates a PENDING_UPLOAD document record.

The client cannot choose the document ID, owner ID, or S3 object key.

The expected object key format is:

    tenants/{tenant_id}/submissions/{submission_id}/{document_id}

## Presigned POST restrictions

Upload requests are limited to:

- PDF: application/pdf
- JPEG: image/jpeg
- PNG: image/png
- Maximum file size: 10 MiB
- URL expiry: 300 seconds

The POST policy requires:

- Exact object key.
- Exact declared Content-Type.
- Exact declared file size.
- SSE-KMS encryption.
- The configured customer-managed KMS key.

The exact-size policy prevents a client from using an upload request
for a different-sized object.

The Content-Type restriction validates the submitted metadata. It does
not inspect the actual file contents or prove that the file matches its
declared format.

## Upload completion verification

The completion endpoint:

1. Rechecks submission authorization and ownership.
2. Verifies document identity and PENDING_UPLOAD state.
3. Verifies the expected tenant-scoped object key.
4. Calls S3 HeadObject.
5. Checks actual ContentLength against the declared size.
6. Checks ContentType against the declared type.
7. Requires ServerSideEncryption to equal aws:kms.
8. Requires SSEKMSKeyId to match the configured KMS key.
9. Requires a non-null S3 VersionId.
10. Persists the accepted VersionId through the document repository.

The document repository updates document and submission counters
transactionally.

A failed verification must not transition the document to UPLOADED.

## Actual content-signature verification

After metadata verification, the application retrieves the exact S3
object version identified by the returned VersionId.

It reads up to 1,024 bytes using a ranged GetObject request and checks
the file signature against the declared content type:

- PDF: `%PDF-`
- JPEG: JPEG file signature (`FF D8 FF`)
- PNG: PNG file signature (`89 50 4E 47 0D 0A 1A 0A`)

Empty, unreadable, or mismatched content is rejected.

The application performs this check before transitioning the document
from PENDING_UPLOAD to UPLOADED.

This is basic file-signature validation, not comprehensive file-format
validation. It does not establish that a file is structurally valid,
safe to render, or free from malicious content. Malware scanning and
content-disarm-and-reconstruction are not implemented.

## Version-specific downloads

S3 bucket versioning is enabled.

After successful completion, the accepted VersionId is stored in
DynamoDB.

Download authorization checks the parent submission before retrieving
the document. Submitters are restricted to their own submissions.
Reviewers can access documents within their authorized tenant.

The download URL includes the stored VersionId. Therefore, a later
upload to the same key does not silently change which object version
the application serves for an already accepted document.

Downloads use attachment Content-Disposition and a short-lived
presigned GET URL.

## Presigned URL replay limitation

A presigned POST is a bearer capability. Anyone possessing the URL and
its required form fields can use it until it expires.

The application does not claim to prevent reuse of an upload URL.

Because bucket versioning is enabled, repeated uploads to the same key
can create additional object versions.

The application records the VersionId observed during completion and
uses that exact version for subsequent downloads.

A replay after completion can therefore create an additional S3
version without changing the version referenced by the document record.

A replay concurrent with completion can result in an additional
unreferenced version. Version-specific downloads still use the version
recorded by the application.

Do not configure automatic noncurrent-version expiration without
considering the relationship between S3 versions and DynamoDB records.
An accepted version must remain available for as long as the application
references it.

## Infrastructure controls

The Terraform-managed bucket configures:

- S3 Block Public Access.
- Bucket-owner-enforced object ownership.
- Bucket versioning.
- Default SSE-KMS encryption.
- S3 Bucket Key.
- HTTPS-only bucket access.
- A bucket policy requiring SSE-KMS and the configured KMS key.
- Incomplete multipart upload cleanup.

The EC2 application role is restricted to the tenant object prefix.
It receives the required S3 object operations and KMS permissions
through S3, subject to the configured encryption context.

The application role does not receive general bucket listing or
object deletion permissions.

## Known limitations

- File-signature validation checks a limited prefix of the uploaded
  object. It does not provide comprehensive file-format validation,
  malware detection, or content-disarm-and-reconstruction.
- No malware scanning or content-disarm-and-reconstruction capability
  is implemented.
- Presigned upload URLs can be replayed before expiration.
- S3 HeadObject can return HTTP 403 for a missing object when the caller
  lacks s3:ListBucket. The application therefore does not assume that
  every missing object produces a 404 response.
- Local unit tests do not prove actual AWS IAM, KMS, bucket-policy, or
  S3 behavior. Those require a controlled AWS integration test.

## Security testing

The unit tests cover:

- Upload size and content-type restrictions.
- Exact-size POST policy conditions.
- Required SSE-KMS algorithm and KMS key.
- Object metadata mismatches.
- Missing object and missing version handling.
- Tenant-scoped object key validation.
- Submission ownership and role restrictions.
- Version-specific download URL generation.
- Rejection of pending documents during download.
