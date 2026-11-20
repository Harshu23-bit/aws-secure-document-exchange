# Cognito JWKS Synchronization

**Project:** AWS Secure Infrastructure Blueprint  
**Document version:** 1.1  
**Review date:** November 21, 2026  
**Implementation status:** Implemented in source code and Terraform; AWS deployment and live operational verification pending.

## 1. Purpose

The JWKS synchronization component maintains a controlled, periodically refreshed copy of the Amazon Cognito User Pool's public JSON Web Key Set (JWKS).

The application can use this document when validating Cognito-issued JWT signatures without depending on an uncontrolled or manually maintained copy of public signing keys.

The synchronization Lambda retrieves the public JWKS over HTTPS, validates its structure and contents, and publishes the validated document to a dedicated Amazon S3 object.

The implementation and Terraform configuration are present in the repository. The AWS resources have not yet been deployed, so live execution and operational behaviour remain unverified.

## 2. Architecture

**AWS services involved**

- Amazon Cognito User Pool — authoritative source of public signing keys.
- AWS Lambda — retrieves, validates, and publishes JWKS.
- Amazon EventBridge Scheduler — triggers periodic synchronization.
- Amazon S3 — stores the synchronized JWKS.
- Amazon CloudWatch Logs — records execution details and errors.
- Amazon CloudWatch Metrics — records successful synchronization heartbeats.
- Amazon CloudWatch Alarms — detect execution errors, failure-queue messages, and stale synchronization.
- Amazon SQS — receives failed Scheduler deliveries and failed asynchronous Lambda executions.
- AWS IAM — separates Lambda execution permissions from Scheduler invocation permissions.

**Data flow**

Cognito JWKS endpoint  
→ EventBridge Scheduler  
→ Lambda execution  
→ HTTPS retrieval and JWKS validation  
→ Read existing S3 object and compare contents  
→ Publish validated JWKS snapshot  
→ Emit CloudWatch success metric

The Lambda publishes the validated object on every successful synchronization, including when its contents are unchanged. The comparison is used to report whether the key material changed.

Two separate SQS destinations capture different failure classes:

- Scheduler delivery failures, when the scheduled invocation cannot be delivered.
- Lambda asynchronous execution failures, when the function exhausts its execution retries.

## 3. Synchronization Implementation

**Lambda function:** `cloudsec-jwks-sync`

**Runtime:** Python 3.12

**Handler:** `handler.handler`

**Source file:** `lambda/jwks_sync/handler.py`

**Terraform definition:** `terraform/environments/dev/jwks-sync.tf`

The Terraform configuration specifies:

| Property | Configuration |
|---|---|
| Runtime | Python 3.12 |
| Architecture | x86_64 |
| Memory | 128 MB |
| Timeout | 30 seconds |
| Reserved concurrency | 1 |
| Environment configuration | Cognito User Pool ID, S3 bucket, metric namespace |
| Lambda code signing | Application Lambda code-signing configuration |

The function performs the following operations:

1. Constructs the Cognito JWKS endpoint using the configured AWS region and User Pool ID.
2. Verifies that the region and User Pool ID are valid and consistent.
3. Retrieves the JWKS over HTTPS.
4. Uses TLS certificate verification and rejects HTTP redirects.
5. Applies a 10-second HTTP timeout and a 65,536-byte response limit.
6. Parses the response as UTF-8 JSON.
7. Rejects duplicate JSON object properties, invalid JSON constants, and malformed documents.
8. Validates the JWKS structure and RSA public-key parameters.
9. Reads the existing S3 object and compares its contents with the canonicalized document.
10. Publishes the validated document to S3 using SSE-S3.
11. Emits a CloudWatch synchronization heartbeat after successful publication.

### JWKS validation controls

The handler enforces the following constraints:

- The JWKS must contain a non-empty `keys` collection.
- Maximum key count: 10.
- Each key must have a unique `kid`.
- Key identifiers cannot exceed 256 characters.
- Only RSA keys using RS256 for signature verification are accepted.
- Required public parameters `n` and `e` must be present and valid.
- RSA modulus size must be between 2,048 and 8,192 bits.
- RSA modulus and exponent values are validated.
- Private RSA parameters are explicitly rejected.
- Non-canonical or malformed Base64URL integer encodings are rejected.

### AWS SDK configuration

The handler configures the AWS SDK with:

- Connection timeout: 2 seconds.
- Read timeout: 3 seconds.
- Standard retry mode.
- Maximum total attempts: 2.

These SDK settings apply to AWS service calls and are separate from the 10-second HTTPS retrieval timeout.

### Publication behaviour

The handler canonicalizes the validated JSON using deterministic serialization.

It reads the existing object before publishing and calculates whether the document contents have changed.

The S3 object is nevertheless written on every successful synchronization. The returned `changed` field indicates whether the contents differed from the previous object.

This allows the object's `LastModified` timestamp to reflect the most recent successful synchronization, even when the signing keys remain unchanged.

## 4. S3 Storage

**Terraform resource:** `aws_s3_bucket.identity_metadata`

**Bucket naming:** Generated using the prefix `cloudsec-identity-metadata-`.

**Object key:** `security/jwks.json`

The exact bucket name is assigned by AWS during resource creation and is not hard-coded in the Terraform configuration.

### Configured bucket controls

| Property | Configuration |
|---|---|
| Object content type | `application/json` |
| Server-side encryption | SSE-S3 (`AES256`) |
| Public access | All four S3 Block Public Access settings enabled |
| Object ownership | Bucket owner enforced |
| Versioning | Enabled |
| Noncurrent version expiration | 30 days |
| Incomplete multipart upload cleanup | 7 days |
| Insecure transport | Explicitly denied by bucket policy |
| Cross-region replication | Not configured |

The bucket policy denies requests that do not use secure transport.

S3 versioning provides recovery capability for previous object versions, subject to the configured noncurrent-version lifecycle expiration.

### Lambda S3 permissions

The Lambda execution role receives:

- `s3:ListBucket` on the dedicated metadata bucket, restricted by an S3 prefix condition for `security/jwks.json`.
- `s3:GetObject` on the exact `security/jwks.json` object.
- `s3:PutObject` on the exact `security/jwks.json` object.

The bucket-level permission supports checking for an existing object while limiting the permitted prefix.

The application role is separately intended to receive read-only access to the published JWKS object. It does not require permission to publish or overwrite the document.

**Deployment status:** Bucket creation, object publication, encryption, versioning, and IAM enforcement have not yet been verified against live AWS resources.

## 5. EventBridge Scheduling

**Schedule name:** `cloudsec-jwks-sync`

**Terraform state configuration:** `ENABLED`

**Schedule expression:**

`cron(0 * * * ? *)`

**Timezone:** UTC

The schedule is configured to run every hour.

| UTC | India Standard Time |
|---|---|
| 00:00 | 05:30 |
| 01:00 | 06:30 |
| 06:00 | 11:30 |
| 12:00 | 17:30 |
| 18:00 | 23:30 |

EventBridge Scheduler invokes the Lambda function through a dedicated execution role:

`cloudsec-jwks-scheduler-role`

The role trust policy:

- Allows assumption by `scheduler.amazonaws.com`.
- Restricts the source account.
- Restricts the source ARN to the default Scheduler schedule group.

The role's permissions allow it to invoke the designated Lambda function and send undelivered scheduled invocations to the Scheduler failure queue.

### Scheduler delivery configuration

- Maximum retry attempts: 2.
- Maximum event age: 3,600 seconds.
- Flexible time window: OFF.

These are Terraform-configured values. Actual schedule state and successful delivery have not been verified in AWS.

## 6. Failure Handling

The implementation separates Scheduler delivery failures from Lambda execution failures.

### EventBridge Scheduler delivery failures

These occur when Scheduler cannot successfully deliver a scheduled invocation to the Lambda target.

**Queue:** `cloudsec-jwks-scheduler-failures`

Configured controls:

- Maximum retry attempts: 2.
- Maximum event age: 3,600 seconds.
- SQS-managed server-side encryption.
- Message retention: 14 days.
- Dedicated CloudWatch alarm for visible messages.

### Lambda asynchronous execution failures

These occur when the Lambda function fails during execution and exhausts its asynchronous invocation retries.

**Queue:** `cloudsec-jwks-sync-failures`

Configured controls:

- Maximum retry attempts: 2.
- Maximum event age: 3,600 seconds.
- SQS-managed server-side encryption.
- Message retention: 14 days.
- Dedicated CloudWatch alarm for visible messages.

The queue is configured as Lambda's asynchronous on-failure destination. It is not being treated as a conventional source-queue dead-letter queue.

The Lambda execution role has permission to send failure records to this queue.

### Retry distinction

The two retry mechanisms serve different purposes:

| Mechanism | Failure being handled | Destination |
|---|---|---|
| Scheduler retry policy | Scheduled invocation delivery failure | `cloudsec-jwks-scheduler-failures` |
| Lambda asynchronous retry policy | Function execution failure | `cloudsec-jwks-sync-failures` |

The Terraform configuration does not explicitly set the SQS visibility timeout. The AWS SQS default is 30 seconds.

## 7. Monitoring and Alerting

### CloudWatch Logs

**Log group:**

`/aws/lambda/cloudsec-jwks-sync`

Configured controls:

- Customer-managed KMS encryption.
- Log retention: 365 days.

The function records synchronization start, successful publication, and execution failures.

### CloudWatch Metrics

**Namespace:**

`CloudSec/JWKS`

**Metric:**

`SyncSuccess`

**Dimension:**

`UserPoolId`

A successful synchronization emits a heartbeat metric with a value of 1 and unit `Count`.

The User Pool ID is supplied through the Lambda environment configuration rather than hard-coded in the handler.

### CloudWatch alarms

Terraform defines the following alarms:

| Alarm | Metric | Purpose |
|---|---|---|
| `cloudsec-jwks-sync-errors` | `AWS/Lambda` — `Errors` | Detect Lambda execution errors |
| `cloudsec-jwks-sync-lambda-dlq` | `AWS/SQS` — `ApproximateNumberOfMessagesVisible` | Detect failed Lambda execution records |
| `cloudsec-jwks-scheduler-dlq-messages` | `AWS/SQS` — `ApproximateNumberOfMessagesVisible` | Detect Scheduler delivery failures |
| `cloudsec-jwks-stale` | `CloudSec/JWKS` — `SyncSuccess` | Detect missing successful synchronization heartbeats |

The stale synchronization alarm evaluates two consecutive hourly periods and treats missing data as breaching.

The alarms are configured to publish notifications through the project's security-alerts SNS topic.

**Deployment status:** Log creation, metric publication, alarm evaluation, and SNS notification delivery have not yet been verified in AWS.

## 8. Local Verification Evidence

The following focused tests were executed locally:

```text
pytest -q tests/test_jwks_sync.py tests/unit/test_jwks.py

84 passed, 8 subtests passed
```
