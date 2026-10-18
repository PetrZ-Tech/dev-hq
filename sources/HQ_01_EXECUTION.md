# HQ_01_EXECUTION — staged work and recovery

## New substantial project
Before implementation, define architecture and a complete technical specification: purpose, boundaries, requirements, components, data, stack, integrations, security, dependencies, deployment/rollback, risks, stages and acceptance criteria. Agree the plan before implementation.

## Execution loop
Approved stage -> bounded substage -> implementation -> verification -> checkpoint/state -> next approved step.

Do not request repeated approval for ordinary steps already covered by the agreed plan. Stop dependent work when scope/architecture changes materially, a new paid solution is introduced, manual user input is required, or an action falls outside existing permission.

## Lifecycle
`scripts/task_lifecycle.py` is the canonical runner. A substantial task should keep one lifecycle run across stages and chat interruptions.

Stages:
`resolve -> context -> freshness -> routing -> checkpoint -> execute -> verify -> quality_gate -> state_handoff -> adr -> backup -> memory -> report`

Required stages cannot be silently skipped. A new execute invalidates old verify/gate evidence. Code/config work uses the real quality-gate runner, not a manually claimed PASS.

## Long operations
Before a potentially long/failure-prone tool, browser, terminal, test, build or external call, register an operation with:
- type and tool;
- short label;
- expected duration/check cadence;
- exact identity/reference when available;
- side-effect flag and stable action key when applicable.

Record progress/result evidence using the lifecycle operation events. A live PID, heartbeat or reachable service proves liveness only.

## Recovery
After interruption, timeout or tool failure:
1. read the same saved run and project state;
2. inspect unresolved operations and exact artifacts read-only;
3. classify outcome as complete / partial / not-started / unknown;
4. record evidence and resolve the operation;
5. continue from the first safe unfinished step.

Never blindly repeat an external side effect with unknown outcome.

## Watchdog
The local watchdog can surface stale/overdue/unknown operation states. It does not continue a stopped ChatGPT turn, perform automatic retries, or certify that an external action succeeded.
