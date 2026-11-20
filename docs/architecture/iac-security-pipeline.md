# Infrastructure-as-Code Security Pipeline

**Project:** AWS Secure Infrastructure Blueprint  
**Document:** Infrastructure-as-Code Security Pipeline  
**Version:** 2.1  
**Review date:** 20 November 2026  
**Status:** CI and security workflows implemented and locally validated; GitHub Actions execution and AWS deployment pending.

---

## 1. Objective

The objective of this pipeline is to integrate security validation into the development lifecycle of the AWS Secure Infrastructure Blueprint.

The pipeline combines infrastructure validation, static security analysis, application testing, dependency vulnerability scanning, secret detection and container image scanning.

The primary objectives are:

- Detect infrastructure misconfigurations before deployment.
- Identify insecure Terraform configurations.
- Enforce consistent infrastructure formatting and validation.
- Detect vulnerable application dependencies.
- Prevent accidental exposure of credentials and secrets.
- Identify container image vulnerabilities.
- Validate backend and frontend changes through automated tests.
- Provide repeatable security checks through GitHub Actions.
- Maintain documented risk decisions for accepted scanner findings.

The pipeline currently validates repository changes. It does not automatically deploy infrastructure to AWS.

## 2. Pipeline Architecture

The implementation uses two GitHub Actions workflows:

| Workflow | File | Responsibility |
|---|---|---|
| CI | `.github/workflows/ci.yml` | Backend, frontend, Terraform, and container build validation |
| Security Scanning | `.github/workflows/security.yml` | Secret detection, dependency auditing, infrastructure security scanning, and container vulnerability scanning |

Both workflows run on:

- Pushes to `main`.
- Pull requests targeting `main`.
- Manual execution through `workflow_dispatch`.

The security workflow additionally runs on a weekly schedule:

```yaml
schedule:
  - cron: "30 2 * * 1"
```

This corresponds to Monday at 02:30 UTC.

Both workflows use:

- `contents: read` permissions.
- GitHub Actions concurrency groups.
- Cancellation of older runs for the same concurrency group.

The workflows do not require AWS deployment credentials.

## 3. Security Toolchain

| Tool | Version / Configuration | Responsibility |
|---|---|---|
| Terraform | 1.17.2 | Infrastructure definition and validation |
| Terraform fmt | Terraform built-in | Formatting consistency |
| Terraform validate | Terraform built-in | Configuration validation |
| TFLint | 0.66.0 | Terraform linting |
| TFLint AWS ruleset | 0.50.0 | AWS-specific Terraform checks |
| Checkov | 3.4.3 | Infrastructure security and compliance scanning |
| Trivy | 0.76.2 locally; GitHub Action v0.36.0 | Container image vulnerability scanning |
| Gitleaks | 8.30.1 locally; GitHub Action v3 | Secret detection |
| Ruff | 0.17.5 in CI | Python linting and formatting |
| pytest | Requirements-managed | Backend unit and integration testing |
| ESLint | Frontend package-managed | Frontend linting |
| Vitest | Frontend package-managed | Frontend testing |
| pip-audit | Installed during CI | Python dependency vulnerability auditing |
| npm audit | Node.js package tooling | Frontend dependency vulnerability auditing |
| Docker Buildx | GitHub Action | Container image building |
| GitHub Actions | Repository workflows | CI and security automation |

Tool availability locally does not independently establish CI integration. The workflow files define which tools actually execute in GitHub Actions.

## 4. Continuous Integration Workflow

File:

`.github/workflows/ci.yml`

The CI workflow contains four independent jobs.

### 4.1 Backend Tests and Quality

Job:

`backend`

Execution environment:

- Ubuntu latest GitHub-hosted runner.
- Python 3.12.
- DynamoDB Local 3.3.2 service container.

The workflow configures local AWS environment variables for testing and disables EC2 metadata access.

Validation sequence:

1. Check out the repository.
2. Set up Python 3.12.
3. Install development dependencies.
4. Install Ruff 0.17.5.
5. Wait for DynamoDB Local to become available.
6. Run Ruff linting.
7. Run Ruff formatting checks.
8. Compile Python application, Lambda, test and script modules.
9. Execute the backend pytest suite.
10. Package Lambda functions.

Commands:

```bash
ruff check .
ruff format --check .
python -m compileall -q app lambda tests scripts
pytest -q
python scripts/package_lambdas.py
```

The DynamoDB Local service allows integration tests to exercise DynamoDB interactions without requiring deployed AWS tables.

The workflow does not use production AWS credentials to execute these tests.

### 4.2 Frontend Tests and Build

Job:

`frontend`

Execution environment:

- Ubuntu latest GitHub-hosted runner.
- Node.js 22.
- Working directory: `frontend`.

Validation sequence:

1. Check out the repository.
2. Set up Node.js.
3. Install dependencies using `npm ci`.
4. Execute frontend tests.
5. Build the frontend.
6. Run ESLint.

Commands:

```bash
npm ci
npm run test:run
npm run build
npm run lint
```

Using `npm ci` ensures that dependency installation follows the committed lockfile.

### 4.3 Terraform Validation

Job:

`terraform`

Working directory:

`terraform/environments/dev`

Validation sequence:

1. Check out the repository.
2. Install Terraform 1.17.2.
3. Install TFLint 0.66.0.
4. Check formatting recursively.
5. Initialize Terraform without a backend.
6. Validate Terraform configuration.
7. Initialize TFLint plugins.
8. Execute recursive TFLint checks.

Commands:

```bash
terraform fmt -check -recursive terraform
terraform init -backend=false -lockfile=readonly
terraform validate
```

TFLint initialization and execution:

```bash
tflint --recursive --init --config "$GITHUB_WORKSPACE/.tflint.hcl"

tflint --recursive \
  --config "$GITHUB_WORKSPACE/.tflint.hcl" \
  --format compact
```

The TFLint configuration enables:

- Terraform recommended rules.
- AWS-specific ruleset version 0.50.0.

The Terraform initialization uses:

- `-backend=false` to avoid configuring a remote state backend.
- `-lockfile=readonly` to avoid modifying the dependency lockfile during CI.

This job validates Terraform configuration without applying infrastructure changes.

### 4.4 Container Build

Job:

`container`

The workflow:

1. Checks out the repository.
2. Configures Docker Buildx.
3. Builds the application image.
4. Inspects the resulting image metadata.

Build command:

```bash
docker buildx build \
  --load \
  --tag cloudsec-platform:ci \
  .
```

The image is built locally within the GitHub Actions runner.

The workflow does not push the image to Amazon ECR or deploy it to EC2.

## 5. Security Scanning Workflow

File:

`.github/workflows/security.yml`

The security workflow contains four independent jobs.

### 5.1 Secret Detection

Job:

`secrets`

Scanner:

Gitleaks GitHub Action v3.

The workflow:

- Checks out the repository with full Git history.
- Runs Gitleaks.
- Uses the GitHub token for action integration.
- Disables automatic pull-request comments.

Configuration:

```yaml
fetch-depth: 0
GITLEAKS_ENABLE_COMMENTS: "false"
```

Full Git history is available for secret detection rather than scanning only the current checkout.

The workflow is intended to identify accidentally committed credentials and other secret patterns.

A successful scan does not prove that no secret has ever been exposed outside the scanned repository history or through other systems.

### 5.2 Dependency Vulnerability Scanning

Job:

`dependencies`

The job audits Python and frontend dependencies.

#### Python dependencies

The workflow:

1. Sets up Python 3.12.
2. Installs pip-audit.
3. Audits `requirements-dev.txt`.

Command:

```bash
pip-audit -r requirements-dev.txt
```

This checks the development dependency set for known vulnerabilities.

#### Frontend dependencies

The workflow:

1. Sets up Node.js 22.
2. Installs dependencies using the frontend lockfile.
3. Runs npm audit.

Command:

```bash
npm audit --audit-level=high
```

The configured threshold is HIGH severity.

The dependency scanning job is intended to fail when the audit command reports findings at or above its configured threshold.

### 5.3 Infrastructure Security Scanning

Job:

`infrastructure`

Scanner:

Checkov 3.4.3.

Installation:

```bash
python -m pip install checkov==3.4.3
```

Execution:

```bash
checkov --config-file .checkov.yaml --quiet
```

The Checkov configuration defines:

- Scan directory: `terraform`.
- Framework: Terraform.
- Output: CLI.
- Compact output enabled.

Checkov evaluates infrastructure configuration against its built-in security policies.

The scan covers relevant areas such as:

- S3 bucket access controls.
- Storage encryption.
- IAM permissions.
- Network exposure.
- EC2 security configuration.
- Logging and monitoring configuration.
- AWS service security settings.

The project maintains a separate exception register:

`docs/security/checkov-exceptions.md`

The exception register documents the rationale, compensating controls and limitations associated with accepted findings.

Accepted exceptions are not equivalent to proof that the associated configurations are risk-free.

#### Custom policy status

The repository currently contains no custom Checkov policy files under:

`policies/checkov/`

Project-specific security decisions are currently represented through Terraform configuration and documented scanner exceptions.

Custom Checkov policies remain a possible future enhancement.

### 5.4 Container Vulnerability Scanning

Job:

`container`

Scanner:

Trivy GitHub Action v0.36.0.

The workflow:

1. Checks out the repository.
2. Configures Docker Buildx.
3. Builds the application image.
4. Scans the image for operating-system and library vulnerabilities.

Build command:

```bash
docker buildx build \
  --load \
  --tag cloudsec-platform:security \
  .
```

Trivy configuration:

| Setting | Value |
|---|---|
| Scan type | Image |
| Package types | OS and library |
| Severity | HIGH, CRITICAL |
| Ignore unfixed | true |
| Exit code on findings | 1 |
| Output | Table |

The configured scan fails when matching HIGH or CRITICAL vulnerabilities are reported under the selected scanner settings.

Unfixed vulnerabilities are excluded from the blocking scan.

This is a deliberate scanning threshold, not evidence that excluded vulnerabilities are harmless.

The workflow does not currently perform a separate Trivy Terraform configuration scan.

Local Trivy configuration scanning has been performed and its findings are documented separately.

## 6. Local Infrastructure Validation

Infrastructure validation is also performed in the local development environment.

The principal checks include:

```bash
terraform fmt -check -recursive terraform
terraform validate
tflint --recursive --config .tflint.hcl
checkov --config-file .checkov.yaml
```

These checks complement the GitHub Actions workflows.

### 6.1 Recorded Terraform and Checkov Results

The latest recorded Terraform validation completed successfully.

Checkov result:

| Result | Count |
|---|---:|
| Passed | 640 |
| Failed | 0 |
| Skipped | 67 |

The skipped checks are documented in:

`docs/security/checkov-exceptions.md`

These are the latest recorded local Checkov results. The GitHub Actions workflows have not yet been executed remotely, so their CI results remain unverified.

The previously identified DynamoDB GSI `hash_key`/`range_key` deprecation warning was resolved by migrating the affected GSI to the provider's `key_schema` configuration. The latest recorded `terraform validate` completed successfully without that warning.

### 6.2 Local Trivy Configuration Scan

A local Trivy configuration scan was also performed.

Recorded command:

```bash
trivy config \
  --tf-vars terraform/environments/dev/terraform.tfvars \
  --format table \
  terraform/environments/dev
```

The recorded scan identified nine findings:

- One HIGH public load balancer finding.
- Five LOW Lambda tracing findings.
- Three HIGH S3 encryption findings.

The earlier public load balancer finding was associated with an outdated configuration and is documented as superseded by the current internal ALB design.

The Trivy configuration scan is not currently part of the GitHub Actions security workflow.

The recorded findings and their review decisions are maintained separately in the security documentation.

## 7. Security Gate Behavior

The workflows use command exit statuses to determine job success or failure.

Examples:

- Ruff failures affect backend CI.
- Backend test failures affect backend CI.
- Frontend test, build or lint failures affect frontend CI.
- Terraform validation or TFLint failures affect Terraform CI.
- Checkov failures affect infrastructure security scanning.
- Gitleaks findings can fail secret detection.
- Dependency audit failures can fail dependency scanning.
- Configured HIGH or CRITICAL Trivy image findings can fail container scanning.

Because these are independent jobs, a failure in one job does not necessarily stop other jobs from executing.

GitHub reports the resulting workflow and job statuses.

### 7.1 Repository Merge Protection

The workflow files do not independently establish whether GitHub branch protection or repository rulesets require all CI and security checks to pass before merging.

Required status checks, reviewer approval requirements and branch protection must be configured and verified separately.

The existence of pull-request workflows alone does not prove that merging is blocked when a security job fails.

## 8. Deployment Security Gate

The current pipeline does not implement automated Terraform deployment.

The following operations are not present in the reviewed workflows:

- Automated Terraform plan generation.
- Terraform plan security scanning.
- Automated infrastructure cost estimation.
- Terraform apply.
- AWS resource deployment.
- Post-deployment AWS configuration validation.

No AWS deployment credentials are configured in the reviewed CI or security workflows.

The current pipeline therefore provides pre-deployment validation rather than a complete deployment lifecycle.

### 8.1 Required Future Deployment Controls

Before introducing automated deployment, the pipeline should include:

1. Terraform plan generation.
2. Review of planned infrastructure changes.
3. Terraform plan security analysis.
4. Cost estimation and budget-impact review.
5. Manual approval for infrastructure deployment.
6. Restricted AWS deployment identity.
7. Short-lived credential or federated authentication.
8. Protected deployment environment.
9. Controlled Terraform apply.
10. Post-deployment configuration validation.
11. Deployment evidence retention.
12. Rollback and recovery procedures.

Production deployment should not be enabled solely because static security scans pass.

## 9. Infrastructure Security Requirements

The security pipeline is intended to detect or help review the following infrastructure risks:

| Security area | Expected control |
|---|---|
| S3 public exposure | Public access restrictions and bucket policy review |
| S3 encryption | Appropriate encryption configuration |
| IAM permissions | Least-privilege policy validation |
| Security groups | Restricted inbound and outbound access |
| EC2 metadata | IMDSv2 enforcement |
| EBS storage | Encryption at rest |
| Network architecture | Public/private segmentation |
| Logging | Required logging and retention configuration |
| KMS | Key policy and encryption configuration review |
| API security | WAF and authorization configuration |
| Lambda security | Runtime, execution role and invocation controls |
| Container security | Image vulnerability scanning |
| Supply chain | Dependency and secret scanning |

Static scanners cannot independently establish application authorization correctness, tenant isolation, runtime behavior or complete AWS security posture.

Those areas require application testing, architecture review and post-deployment validation.

## 10. Exception Management

Scanner findings that are intentionally retained are documented in:

`docs/security/checkov-exceptions.md`

The register records:

- Affected scanner checks.
- Affected Terraform resources.
- Technical rationale.
- Compensating controls.
- Residual limitations.
- Conditions requiring reassessment.

The exception register covers accepted Checkov findings and documented Trivy configuration findings.

Exceptions should be:

- Specific to the affected resource and finding.
- Supported by technical reasoning.
- Reviewed against the current architecture.
- Reassessed when requirements or implementation change.

A scanner exception must not be treated as a blanket waiver for unrelated resources.

## 11. Pipeline Security and Supply-Chain Considerations

The current workflows implement several useful controls:

- Read-only repository permissions.
- No AWS deployment credentials in the reviewed workflows.
- Dependency installation through committed lockfiles where configured.
- Explicit versions for Terraform, TFLint, Checkov and Ruff.
- Separate CI and security workflows.
- Full Git history for Gitleaks scanning.
- Container image vulnerability scanning.
- Scheduled security scanning.

Additional hardening opportunities remain:

- Maintain immutable commit-SHA pins for third-party GitHub Actions and review pin updates.
- Review third-party action permissions and provenance.
- Evaluate artifact attestations and build provenance.
- Introduce controlled artifact signing and verification.
- Define dependency update and vulnerability remediation policies.
- Configure and verify branch protection.
- Establish protected deployment environments.
- Introduce OIDC-based AWS authentication if deployment is automated.
- Retain security scan reports as reviewable build evidence.

Third-party GitHub Actions in the current workflows are pinned to full commit SHAs. This reduces the risk of an action's referenced code changing when a mutable version tag is updated. Pins still require periodic review and controlled updates.

The existing Lambda code-signing infrastructure is a separate artifact-integrity control. It does not by itself establish that the complete CI build and release process is audited or enforced.

## 12. Current Implementation Status

| Component | Status |
|---|---|
| Backend CI | Implemented |
| DynamoDB Local integration testing in CI | Implemented |
| Ruff linting | Implemented |
| Ruff formatting checks | Implemented |
| Python compile checks | Implemented |
| Backend pytest execution | Implemented |
| Lambda packaging in CI | Implemented |
| Frontend testing | Implemented |
| Frontend production build | Implemented |
| Frontend ESLint | Implemented |
| Terraform formatting validation | Implemented |
| Terraform initialization and validation | Implemented |
| TFLint AWS ruleset | Implemented |
| Checkov Terraform scanning | Implemented |
| Gitleaks secret detection | Implemented |
| Python dependency auditing | Implemented |
| Frontend dependency auditing | Implemented |
| Container image build in CI | Implemented |
| Trivy container vulnerability scanning | Implemented |
| Local Trivy Terraform configuration scanning | Executed locally; not in CI |
| Custom Checkov policies | Not implemented |
| Terraform plan scanning | Not implemented |
| Automated cost estimation | Not implemented |
| GitHub immutable action SHA pinning | Implemented — third-party actions pinned to full commit SHAs |
| Required branch status checks | Not established by workflow files |
| Automated Terraform deployment | Not implemented |
| Post-deployment AWS validation | Pending deployment |

## 13. Deployment Readiness

The current pipeline provides a meaningful pre-deployment validation layer.

It does not constitute a complete production deployment pipeline.

The following remain necessary before AWS infrastructure can be deployed through automation:

- Plan-based change review.
- Deployment identity and credential controls.
- Approval and protected-environment configuration.
- Cost-impact assessment.
- Terraform apply workflow.
- Post-deployment security validation.
- Evidence retention.
- Operational monitoring and recovery procedures.

No AWS resources have been deployed as part of the current project validation.

The Terraform state contains zero managed resources.

## 14. Conclusion

The project implements separate CI and security workflows that validate application code, Terraform configuration, dependencies, secrets and container images.

Terraform formatting, validation, TFLint and Checkov provide infrastructure-focused static analysis.

Backend and frontend tests provide application-level validation, while Gitleaks, dependency auditing and Trivy extend the pipeline's security coverage.

Accepted scanner findings are documented rather than silently treated as resolved.

The current implementation is a pre-deployment CI and security validation pipeline. Automated infrastructure planning, approval, deployment, and post-deployment validation remain future implementation requirements.

A successful pipeline run demonstrates that the configured checks passed for that revision. It does not independently prove that deployed AWS infrastructure is secure or production-ready.
