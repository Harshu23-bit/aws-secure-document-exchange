# Experimental Dockerfiles

These Dockerfiles document security investigation experiments.
They are not production build definitions.

| Dockerfile | Experiment |
|---|---|
| Dockerfile.bookworm-test | Compared Debian Bookworm against Trixie |
| Dockerfile.ncurses-test | Investigated ncurses executable removal |
| Dockerfile.sqlite-test | Investigated removal of Python SQLite support |
| Dockerfile.trixie-upgrade-test | Tested a full Debian package upgrade |

The experiments did not replace the selected production candidate.

Production Dockerfile:
`../../../Dockerfile`

Investigation results:
`../../../evidence/container-security/experiments/`

Security assessment:
`../../../docs/security/container-vulnerability-risk-assessment.md`
