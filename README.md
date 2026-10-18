# Dev HQ

A repository-based development control plane for ChatGPT projects.

Dev HQ is not an autonomous coding agent. It is a set of project instructions, lifecycle rules, local scripts, quality gates, recovery procedures, skills and a lightweight watchdog that make long ChatGPT development sessions more structured and recoverable.

## What it provides

- architecture/TZ/stage-first workflow for new projects;
- explicit lifecycle runs with checkpoints and evidence;
- operation tracking for long or failure-prone tool calls;
- recovery rules after interrupted chats or tool failures;
- a local watchdog for task/runtime diagnostics;
- quality-gate and secret checks before completion;
- verified local backups;
- reusable tool skills and six compact ChatGPT Project Sources;
- separation between reusable HQ logic and private environment/project state.

## Core idea

The public repository contains reusable rules and tooling. Your machine, accounts, project registry, credentials, production state and runtime logs stay local and are intentionally excluded from Git.

## Quick start

1. Clone this repository into a local folder.
2. Create or choose a projects directory. By default Dev HQ uses `~/Projects`.
3. Optionally set `DEV_HQ_PROJECTS_ROOT` to another directory.
4. Copy the contents of `CHATGPT_PROJECT_INSTRUCTIONS.md` into your ChatGPT Project instructions.
5. Add the six files from `sources/` to the ChatGPT Project as Sources.
6. Copy the example files you need and remove `.example` from their private local copies.
7. Connect only the tools/connectors you actually use.
8. Run the local watchdog when needed:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-hq.ps1
```

9. Run tests:

```powershell
python -m pytest -q
```

## Configuration

`DEV_HQ_PROJECTS_ROOT` is the only important path setting for the core scripts. If it is not set, the scripts use `~/Projects`.

Optional watchdog settings are documented in `.env.example`. The repository does not load `.env` automatically; set environment variables through your shell or preferred local secret/config manager.

## Public vs private files

Public/reusable files include the lifecycle scripts, quality gate, watchdog, staged execution rules, security boundaries, templates and skills.

Private files such as `ENVIRONMENT.md`, `PROJECTS_REGISTRY.md`, `PROJECT_STATE.md`, runtime logs, handoffs, records, credentials and `.env` files are ignored by Git. Use the corresponding `.example.md` files as templates.

## Security model

- Never commit real API keys, tokens, passwords, cookies, service-account files or private keys.
- Keep production endpoints and infrastructure inventory in private local files unless they are intentionally public.
- A secret that has ever been committed should be rotated even after it is removed from the working tree.
- Run `scripts/public_release_audit.py` before every public release.

## Architecture

The normal flow is:

```text
User request
  -> ChatGPT Project instructions
  -> relevant Source / skill
  -> staged execution
  -> lifecycle run
  -> tool / connector
  -> verification
  -> quality gate
  -> checkpoint / state update
  -> report
```

For long operations, Dev HQ records operation identity, deadline and evidence. A heartbeat or running process is not treated as proof of progress.

## Important limitation

The watchdog observes local state and operation metadata. It does not continue a stopped ChatGPT turn, automatically retry external side effects, or replace explicit verification.

## Repository status

This directory is the sanitized public edition. Before publishing changes, run the release audit and review the findings.

## License

MIT — see `LICENSE`.
