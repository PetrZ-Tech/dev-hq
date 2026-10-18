# External Coding Handoff

Use a handoff only when delegating part of the work to an external coding executor is justified.

## Before handoff
- resolve the exact project;
- read current state and Git status;
- identify the smallest relevant file set;
- state the task, desired outcome, scope and constraints;
- define acceptance criteria and verification;
- choose a suitable complexity/reasoning level via `MODEL_ROUTING.md`;
- exclude credentials and secret files.

## Build
Use `scripts/build_codex_handoff.py` to create a bounded package in local ignored `handoffs/`.

A generated handoff is only a prepared artifact. It does not prove that an executor was launched, that code was changed, or that checks passed.

## After return
Dev HQ must independently inspect the actual project changes and continue its own lifecycle stages: verify -> quality gate -> state/checkpoint -> backup/memory -> report.
