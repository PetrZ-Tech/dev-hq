# HQ_03_QUALITY_SAFETY — verification and permissions

## Permissions
Ordinary reversible edits and local tests inside the managed projects root are allowed when they are part of the agreed task. Reading normal non-secret project files for diagnosis does not require repeated confirmation.

Require explicit authorization for actions such as:
- production deploys/migrations/live writes;
- external messages, publishing, payments or access changes;
- destructive, bulk or difficult-to-reverse operations;
- operating-system/service/network/security configuration changes outside the project scope;
- reading/changing secrets, private keys, credentials or protected account data when not already clearly authorized.

Do not commit, push or release without an explicit request.

## Secrets
Never print, copy into reports, store in memory/state, or commit API keys, tokens, passwords, cookies, private keys or recovery credentials. Report secret-scan findings by location/type, not by value.

## Quality Gate
`scripts/quality_gate.py` checks project scope, Git/diff health, potential secrets, applicable safe tests/typecheck/lint/build and current acceptance criteria.

- `PASS`: all required applicable checks are verified.
- `WARN`: verification is incomplete or advisory.
- `FAIL`: a required check failed or safe preflight refused execution.

Dirty Git state by itself is not failure. Do not bypass a quality-gate refusal merely to produce a PASS.

For code/config work, run the gate through the lifecycle. Docs/read-only work may skip the mechanical gate with a reason, but substantive verification is still required.

## Completion
Files existing is not proof that behavior works. Verify at the appropriate level: read-back, tests, build, runtime behavior or external result evidence. Report `PARTIAL`, `BLOCKED` or `WARN` accurately instead of presenting them as success.
