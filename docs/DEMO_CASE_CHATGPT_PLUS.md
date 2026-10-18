# Demo Case — Build a Project in ChatGPT Plus Without Codex

This is a **reproducible demonstration script** for Dev HQ. It shows how to develop a small real application from normal ChatGPT chat plus connected local tools, without making Codex or another external coding agent part of the required path.

It is intentionally written as a demo you can repeat, record and inspect. It is not a claim that the sample application itself is bundled in this repository.

## Goal

Build a small **Issue Desk** web application from scratch with:

- issue creation;
- title, description, priority and status;
- list and detail views;
- status transitions;
- local persistence;
- basic validation;
- automated tests;
- a README with run instructions.

The point of the demo is not the application idea. The point is to show the Dev HQ workflow around it.

## Constraints

- Use normal ChatGPT chat as the primary interface.
- Use direct local file/terminal tools when available.
- Do not use Codex for implementation.
- Do not deploy or publish anything externally.
- Keep all work inside a new local project directory.
- Run real tests before calling a stage complete.

## Phase 1 — Ask for architecture before code

Start a new ChatGPT Project configured with Dev HQ and send:

> I want to build a small Issue Desk web application from scratch. Do not write code yet. First produce the complete architecture, technical specification, development stages, tests, acceptance criteria, risks and decision points. The app needs issue creation, priority, status transitions, local persistence and a simple web UI.

Expected Dev HQ behavior:

1. resolve the new project scope;
2. define architecture and boundaries;
3. choose a minimal stack;
4. split implementation into bounded stages;
5. define tests and acceptance criteria per stage;
6. stop for approval before implementation.

This is the first visible difference from ad-hoc "vibe coding": implementation does not begin before the target is explicit.

## Phase 2 — Approve the plan

After reviewing the architecture, answer:

> Architecture and stages approved. Start Stage 1 and continue stage by stage. After each stage run the agreed checks, save the checkpoint/state and only then continue.

Dev HQ should create or update the lifecycle run and begin the first bounded implementation stage.

## Phase 3 — Direct implementation from ChatGPT

The normal execution loop is:

```text
ChatGPT
  -> read current project state
  -> inspect the smallest relevant file set
  -> edit/create files with the connected filesystem tool
  -> run tests or checks with the connected terminal tool
  -> inspect actual results
  -> update lifecycle/checkpoint
  -> continue to the next approved stage
```

No external coding agent is required in this loop.

A practical stage sequence could be:

1. **Project scaffold** — application structure and test runner.
2. **Domain model** — issue entity, validation and persistence.
3. **API** — create/list/read/update-status endpoints.
4. **Web UI** — list, create form, issue details and status action.
5. **Regression tests** — domain + API + critical UI behavior where practical.
6. **Documentation** — run instructions, architecture note and current state.

## Phase 4 — Demonstrate a long operation

During a test/build or another potentially slow action, Dev HQ should register the operation before execution.

The Watchdog can then show that the task is working, waiting, overdue or unresolved. Importantly, a running process is not automatically interpreted as useful progress.

If the operation exceeds its expected time, the correct behavior is:

1. inspect the saved operation identity;
2. inspect the actual process/result read-only;
3. determine whether the result is available, failed or unknown;
4. continue or recover based on evidence;
5. do not blindly run the same side effect again.

## Phase 5 — Simulate an interrupted chat

To demonstrate recovery, stop after a verified stage and start a new chat in the same ChatGPT Project.

Send:

> Continue the Issue Desk project from the last verified checkpoint. First recover the saved state and lifecycle run. Do not repeat completed work.

Expected behavior:

- read the project registry/state;
- recover the same lifecycle run;
- identify the last verified stage;
- inspect unresolved operations if any;
- continue from the first unfinished safe step.

The user should not have to retell the whole project.

## Phase 6 — Quality Gate

Before declaring the project technically complete, Dev HQ should run the applicable checks and verify the acceptance criteria.

For the demo, capture evidence such as:

```text
pytest / project test command -> PASS
lint or typecheck if configured -> PASS
application smoke check -> PASS
public/private secret scan -> PASS
acceptance criteria -> confirmed
```

If a required check is missing or uncertain, the result should be WARN/PARTIAL rather than a fake PASS.

## Phase 7 — Final report

The final ChatGPT response should contain four things:

1. what was implemented;
2. exact checks that passed;
3. anything still open;
4. where the runnable result is located.

Technical completion and user delivery are treated as separate events.

## What to show in a video

A compact 3–5 minute demo can show:

1. an empty project directory;
2. the architecture/specification produced before coding;
3. the approved stage plan;
4. ChatGPT editing files directly through the local tool;
5. a real test command and its output;
6. the Watchdog page;
7. the saved `PROJECT_STATE.md` / lifecycle checkpoint;
8. a new chat recovering the exact project without re-explaining it;
9. the final working application;
10. `git diff` proving what ChatGPT created.

Keep Codex closed during the recording. The point is to show that Dev HQ is the development process, not a wrapper around a coding agent.

## Evidence checklist

For a credible public demo, keep these artifacts:

- [ ] architecture/specification generated before implementation;
- [ ] approved development stages;
- [ ] lifecycle run created;
- [ ] at least one registered long operation;
- [ ] Watchdog screenshot or screen recording;
- [ ] real test output;
- [ ] project state after an intermediate checkpoint;
- [ ] successful recovery in a new chat;
- [ ] final project `git diff` / commit;
- [ ] final application running locally;
- [ ] no Codex execution in the implementation path.

## What this demo proves

If all evidence above is captured, the demo supports a narrow, testable claim:

> A multi-stage software project can be coordinated and implemented from normal ChatGPT chat with direct local tools, durable project state, staged verification and recovery, without requiring Codex as the coding executor.

It does **not** prove that every project should avoid coding agents, that ChatGPT can continue autonomously after a stopped turn, or that Dev HQ replaces engineering review. External executors remain optional tools for cases where they provide a real advantage.
