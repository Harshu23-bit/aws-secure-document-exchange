# S3 Document Version Hygiene Security Review

**Project:** AWS Secure Infrastructure Blueprint  
**Document:** S3 Document Version Hygiene Security Review  
**Version:** 1.1  
**Review date:** 20 November 2026  
**Status:** Implementation and local tests validated; live AWS validation pending.

## Scope

This document describes the security controls implemented by the
document version hygiene Lambda.

The Lambda removes unaccepted S3 object versions and delete markers
created when a presigned upload URL is replayed.

It preserves the exact S3 VersionId accepted by the application and
removes the document's hygiene scheduling attributes from DynamoDB
only after successful S3 verification.

Reviewed components:

- `lambda/document_version_hygiene/handler.py`
- `terraform/environments/dev/document-version-hygiene.tf`
- `terraform/environments/dev/dynamodb.tf`
- `tests/test_document_version_hygiene.py`
- `tests/integration/dynamodb/test_document_version_hygiene_lambda.py`
- `tests/integration/conftest.py`
- `tests/integration/dynamodb/conftest.py`

## Candidate validation

Before performing S3 operations, the Lambda validates the DynamoDB
candidate.

Validation requires:

- `entity_type` to equal `DOCUMENT`.
- Document status to equal `UPLOADED`.
- Tenant, submission and document identifiers to be valid.
- DynamoDB partition and sort keys to match the document identity.
- S3 object key to match the canonical tenant-scoped key.
- Accepted VersionId to be present and not equal to the literal
  `null`.
- Hygiene shard and GSI partition key to match the expected shard.
- Timestamps to be canonical and timezone-aware.
- Upload URL expiry to precede reservation expiry.
- Hygiene deadline to equal upload URL expiry plus the configured
  24-hour grace period.
- Hygiene deadline to have passed.

Invalid candidates are rejected before S3 listing, deletion or
DynamoDB index modification.

The GSI projection includes `entity_type`, allowing the Lambda to
validate the entity type using the projected candidate.

## S3 version discovery

The Lambda uses `ListObjectVersions` to discover versions and delete
markers for the expected object key.

Controls include:

- Prefix-scoped S3 listing.
- Exact object-key matching after listing.
- Pagination through key and version ID markers.
- Validation of pagination indicators and next markers.
- Detection of invalid or non-advancing pagination markers.
- A maximum of 5,000 exact-key versions and delete markers per
  document.

The version limit prevents unbounded accumulation of S3 version
metadata in Lambda memory.

If the limit is exceeded, processing fails closed. The Lambda does
not proceed with deletion or remove the DynamoDB hygiene index.

## Accepted-version protection

The accepted VersionId is obtained from the validated DynamoDB
document record.

Before deletion, the Lambda verifies that the accepted version
exists in the exact-key S3 version collection.

Deletion excludes the accepted VersionId.

The Lambda deletes:

- All other versions belonging to the exact object key.
- All delete markers belonging to the exact object key.

Deletion requests are batched in groups of at most 1,000 objects.

S3 deletion responses are checked for errors. A deletion error
prevents successful finalization.

After deletion, the Lambda lists the object versions again and
requires:

- Exactly one remaining object version.
- The remaining version to have the accepted VersionId.
- No remaining delete markers.

The DynamoDB hygiene index is not removed unless this verification
succeeds.

## Conditional DynamoDB finalization

After successful S3 verification, the Lambda removes `GSI3PK` and
`GSI3SK` from the document record.

The conditional update verifies:

- Document status remains `UPLOADED`.
- Entity type remains `DOCUMENT`.
- Tenant, submission and document identities remain unchanged.
- Object key remains unchanged.
- Accepted VersionId remains unchanged.
- Relevant expiry and hygiene timestamps remain unchanged.
- GSI partition and sort keys remain unchanged.

A conditional-check failure is treated as a concurrent state change.
The Lambda does not overwrite the newer record state.

Other DynamoDB errors propagate as failures.

## Lambda execution safeguards

The Lambda has a configured timeout of 300 seconds and reserved
concurrency of one.

The handler also limits the number of candidates processed per
invocation.

A five-second execution-time buffer is used for S3 operations.

Before every S3 version-listing request, the Lambda checks the
remaining execution time.

Before every S3 deletion batch, it performs the same check.

Post-deletion verification uses the same time-aware pagination
function.

If the remaining execution time is 5,000 milliseconds or less,
the handler starts no additional S3 listing or deletion operation.

The execution context is passed from the Lambda entry point through
the shard-processing and cleanup functions.

The optional context argument preserves compatibility with direct
unit-test calls and other callers that do not supply a Lambda context.

## Infrastructure controls

The Terraform configuration provides:

- Python 3.12 Lambda runtime.
- 300-second Lambda timeout.
- 128 MB configured memory.
- Reserved concurrency of one.
- Scheduled execution every 15 minutes.
- Bounded asynchronous invocation retries.
- Lambda asynchronous failure destination to SQS.
- EventBridge Scheduler retry configuration and dead-letter queue.
- CloudWatch alarms for Lambda errors and dead-letter queues.

The Lambda IAM policy is restricted to the required operations:

- Query the document hygiene GSI.
- Update the document DynamoDB table.
- List object versions under the tenant object prefix.
- Delete object versions under the tenant object prefix.
- Write Lambda logs.
- Send failed invocation messages to the configured SQS destination.

The Lambda does not receive general S3 object deletion permissions
outside its configured tenant object prefix.

Reserved concurrency of one prevents overlapping executions of this
Lambda function.

## Failure handling

The Lambda fails closed in the following cases:

- Invalid or inconsistent DynamoDB candidate.
- Accepted S3 version is missing.
- S3 listing or pagination failure.
- Version history exceeds the configured limit.
- S3 deletion reports errors.
- Post-deletion verification finds unexpected versions or markers.
- DynamoDB finalization fails unexpectedly.
- Insufficient Lambda execution time for another S3 operation.

The hygiene index remains available for retry when cleanup does not
complete successfully.

The handler records failed candidate processing and raises an error
when the invocation has one or more failures, allowing configured
asynchronous retry and failure-destination handling to operate.

## Security findings and limitations

### Findings addressed

1. Candidate validation now requires `entity_type = DOCUMENT`
   before any destructive S3 operation.
2. The DynamoDB GSI projection includes `entity_type` so that
   projected candidates can be validated.
3. S3 version discovery has a maximum of 5,000 exact-key entries.
4. Lambda execution-time checks prevent new S3 listing and deletion
   operations from starting inside the five-second safety buffer.
5. The accepted VersionId is preserved and verified before
   DynamoDB hygiene scheduling attributes are removed.

### Remaining limitations

- Presigned upload URLs remain replayable until expiration.
  This Lambda cleans up additional versions; it does not prevent
  replay.
- An object with more than 5,000 exact-key versions or delete
  markers fails closed and requires operational investigation.
- A Lambda timeout or transient AWS service failure can leave
  cleanup partially completed. Retry handling is configured, but
  successful cleanup is not guaranteed during an outage.
- Reserved concurrency of one limits throughput. Increasing
  concurrency or introducing multiple workers would require a
  separate concurrency and coordination review.
- Unit tests and DynamoDB integration tests do not prove live S3,
  IAM, KMS, EventBridge or Lambda behavior.
- No live AWS deployment or destructive S3 integration test is
  claimed by this review.

## Security testing

### Unit tests

`tests/test_document_version_hygiene.py`

Coverage includes:

- Candidate identity and attribute validation.
- Rejection of invalid entity types before S3 operations.
- Timestamp and hygiene deadline validation.
- Exact-key filtering.
- S3 pagination and marker validation.
- Version-history limit enforcement.
- Accepted-version preservation.
- Batched deletion.
- S3 deletion error handling.
- Post-deletion verification.
- Conditional DynamoDB index removal.
- Lambda execution-time checks before pagination and deletion.
- Verification stopping when the execution-time buffer is reached.

Result:

- 74 passed.

### DynamoDB integration tests

`tests/integration/dynamodb/test_document_version_hygiene_lambda.py`

Coverage includes:

- DynamoDB GSI projection.
- Eligible candidate processing.
- Hygiene index removal after successful cleanup.
- Preservation of the accepted version.
- Removal of additional versions and delete markers.
- Exact-key protection against lookalike object keys.
- Fail-closed behavior when the accepted version is missing.
- S3 failure handling.
- Conditional update races.
- Invalid null VersionId handling.

Result:

- 8 passed.

### Full backend regression suite

Latest recorded result (20 November 2026):

- 969 passed.
- 8 subtests passed.

This is the full backend regression result, not the individual test count for this Lambda's targeted test files.

### Terraform validation

- Recursive Terraform formatting check passed.
- Terraform formatting check passed.
- Terraform validation succeeded without the previously identified DynamoDB GSI `hash_key`/`range_key` deprecation warning, which was resolved by migrating the affected GSI to `key_schema`.
- No Terraform apply or AWS deployment was performed.

## Review conclusion

The document version hygiene implementation validates candidate
identity before destructive operations, preserves the accepted S3
version, verifies cleanup before changing DynamoDB scheduling state,
and applies bounded execution and version-history safeguards.

The reviewed unit tests, DynamoDB integration tests, full backend
regression suite and Terraform validation passed.

No live AWS security validation is claimed.
