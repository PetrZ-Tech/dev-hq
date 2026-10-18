# Resource Control

Resource Control keeps expensive tools, deep research and high-reasoning routes proportional to the task.

## Tiers

| Tier | Typical use |
|---|---|
| `LOW` | local read-only work, navigation, small edits, lightweight checks |
| `NORMAL` | ordinary development, standard connected-tool calls, normal analysis |
| `HIGH` | deep debugging, architecture, large-context work, substantial research |
| `EXTREME` | exceptional high-risk or unusually difficult work requiring the strongest suitable configuration |

## Rules

1. Choose the lowest tier that can satisfy the acceptance criteria safely.
2. Do not escalate only because a task has many files or takes time.
3. Prefer direct tools and focused retrieval over broad repeated searches.
4. Record measurable local usage only when it is useful for diagnostics or planning.
5. The local resource ledger is telemetry, not billing data and not proof of platform allowance usage.
6. If current platform usage/limits are unavailable, report them as unknown rather than estimating them from the local ledger.
7. For `EXTREME`, record a short reason why the normal/high route is insufficient.

## Local ledger

Use `scripts/resource_tracker.py` for optional local event tracking. Never put API keys, tokens, authorization headers or other credentials into ledger notes.
