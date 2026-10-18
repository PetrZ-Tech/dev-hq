# Security Policy

## Reporting a vulnerability
Do not open a public issue containing credentials, tokens, private infrastructure details or exploit material that would expose another user's environment. Use the repository owner's private security-reporting channel when one is configured.

## Repository hygiene
Before publishing or releasing:

```powershell
python .\scripts\public_release_audit.py --root .
```

For known private markers, add repeated `--forbid` arguments. The audit reports locations/types only and intentionally does not print matched secret values.

## Secret handling
- Never commit API keys, passwords, access/refresh tokens, cookies, private keys, recovery codes or service-account credentials.
- Keep `.env`, runtime state, project registries and infrastructure inventory local and ignored.
- If a real credential has ever entered reachable Git history, treat it as compromised and rotate/revoke it even after removing the file.
- Do not rely on `.gitignore` as the only secret-control mechanism; run the release audit before public commits/releases.

## Scope
The audit reduces accidental disclosure risk but is not a formal security certification. Review generated documentation, screenshots, archives and binary files manually before release when they are added.
