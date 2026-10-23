---
id: WORDSTAT-001
title: Ignore the revoked XML River key in git history by fingerprint
status: queue
attempts: 0
blocked: false
blocked_reason: null
phase: null
tests_hash: null
publish_stage: null
created_by: architect
approved_by: human
worker: claude-code
type: chore
owns_paths:
- .gitleaksignore
test_paths: []
docs: none
tools: []
worker_args: null
decision: false
visual: null
depends_on: []
budget_usd: null
epic: null
spec_refs: []
checks:
- gitleaks git --redact --no-banner --no-color .
resident: null
tool: null
pr: null
---

Create .gitleaksignore with exactly one line (a gitleaks fingerprint, no secret value in the repo): f0e42064c1f64a025bc473a4f3fbf1147ee7e3ba:README.md:generic-api-key:29. It is the finding of the key the Human revoked, in an old commit. Check: gitleaks git reports 'no leaks found'.

## Read first

- `.gitleaks.toml`
- `README.md`

## Out of scope

- Editing any other file; rewriting git history; ignoring any other finding
