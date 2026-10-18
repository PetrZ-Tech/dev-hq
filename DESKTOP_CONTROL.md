# Optional Desktop Control

Desktop/GUI automation is optional. Dev HQ should use it only when a task cannot be completed more reliably through direct files, APIs or connectors.

## Preferred order
1. direct connector/API;
2. structured UI automation/accessibility controls;
3. screenshot-based interaction when necessary;
4. raw mouse/keyboard only as a fallback.

## Safety
- Treat passwords, 2FA codes and recovery credentials as protected input.
- System settings, services, network/security configuration and destructive GUI actions require explicit scope.
- Verify the result after every meaningful GUI write.
- Do not assume a desktop-control tool is installed merely because a skill/document exists in this repository.

## Watchdog integration
If a compatible local desktop-control MCP endpoint is available, set `DEV_HQ_DESKTOP_CONTROL_PORT`. Without it, UI observation remains degraded/unknown and core Dev HQ still works.
