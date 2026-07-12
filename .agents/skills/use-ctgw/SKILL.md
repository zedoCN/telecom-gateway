---
name: use-ctgw
description: Safely use the ctgw command-line client to inspect supported China Telecom residential gateways and manage exact port mappings or request a reboot. Use when Codex needs gateway status, device information, connected-device lists, JSON output, port-mapping inspection or a user-authorized single mapping change on hardware managed through ctgw.
---

# Use ctgw

Operate supported gateways through the `ctgw` CLI while keeping credentials and device identifiers out of commands, logs, and reports.

## Prepare

1. Resolve the executable in this order: use this Skill's executable `bin/ctgw` when bundled, otherwise use `command -v ctgw`; if working in the source repository, use `go run ./cmd/ctgw` or build `bin/ctgw`.
2. Run `ctgw help` and `ctgw version` before relying on a remembered command surface.
3. Confirm that the target gateway is owned by the user or explicitly authorized for management.
4. Run `ctgw auth status`. Prefer a verified profile saved with `ctgw --username NAME --password-stdin auth login`; otherwise use `CTGW_URL` and `CTGW_USERNAME` plus an existing secure `CTGW_PASSWORD` value or `--password-stdin`.
5. Keep global flags before the command.

Read [references/commands.md](references/commands.md) when exact command flags or output choices are needed.

## Inspect

Start with the narrowest read-only command:

```bash
ctgw status
ctgw info
ctgw devices
ctgw port list
```

Use `--json` for parsing. Do not use `info --show-sensitive` unless the user explicitly needs those local fields. Never reproduce sensitive output in chat, committed files, issues, or logs.

## Change

Only perform a mutation when the user explicitly requests it.

1. Run `ctgw port list` immediately before a mapping change.
2. Identify one exact rule name or one complete new rule.
3. Preserve an already verified recovery path to the gateway.
4. Run the exact mutation with `--yes`; do not bypass this gate.
5. Run `ctgw port list` again and verify only the intended object changed.
6. Report the requested change and read-back result without copying unrelated rules or sensitive fields.

For reboot, confirm the expected outage and recovery path first, then use `ctgw reboot --yes`. Re-check reachability after the device has had sufficient time to return.

## Refuse unsafe shortcuts

- Do not invent bulk delete, bulk disable, bulk enable, wildcard, or implicit replacement commands.
- Do not test write behavior against a live gateway merely to discover its semantics.
- Do not expose credentials through `echo`, process arguments, shell traces, tool output, or generated scripts.
- Do not read passwords back from the OS keyring or copy the user profile into reports. Let `ctgw` resolve the saved credential internally.
- Do not claim a model is supported without project documentation and verified fixtures.
