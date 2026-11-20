# Container Security Evidence

This directory contains machine-readable Trivy scan reports.

## Baseline

The baseline directory contains historical and selected image scans.

- 0.1.1: Historical baseline
- 0.1.2: Historical baseline
- 0.1.3: Selected hardened image candidate

## Experiments

The experiments directory contains reports from rejected or
investigative approaches.

- Bookworm base image comparison
- Trixie package upgrade
- SQLite support removal

Experimental Dockerfiles are maintained in:
`tests/docker/experimental/`

The full investigation and residual-risk assessment is documented in:
`docs/security/container-vulnerability-risk-assessment.md`
