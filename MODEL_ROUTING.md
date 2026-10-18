# Model Routing

Dev HQ should select the least expensive/limited model configuration that is still sufficient for the task. Exact model names are intentionally not hardcoded because availability differs by account and changes over time.

## Complexity levels

| Complexity | Typical work | Recommended reasoning |
|---|---|---|
| `simple` | formatting, navigation, tiny edits, straightforward checks | Low / fast |
| `normal` | routine coding, file analysis, planning, ordinary debugging | Medium |
| `complex` | architecture, hard debugging, multi-system reasoning, security-sensitive design | High |
| `extreme` | unusually ambiguous, high-risk or technically difficult work where failure is expensive | Highest suitable setting available |

## Selection rules

1. Start with the smallest sufficient configuration.
2. Increase reasoning/model capability because of task complexity or risk, not merely because the task is long.
3. Prefer the user's currently available default model for ordinary work.
4. Use a stronger reasoning model/configuration when evidence shows the normal route is insufficient.
5. Do not claim a model switch unless the active configuration is actually known.
6. Model names in generated handoffs are recommendations only; the executor must use an available equivalent if the named configuration does not exist.

## Local preference

Users may keep account-specific preferences in an ignored local file such as `MODEL_ROUTING.local.md`. Public reusable rules must not depend on that file.
