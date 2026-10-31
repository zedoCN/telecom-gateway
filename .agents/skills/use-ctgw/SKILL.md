---
name: use-ctgw
description: Inspect supported China Telecom gateways and manage exact port mappings or request a reboot through the bundled Python ctgw CLI. Use for gateway status, device information, connected devices, JSON inspection, or a user-authorized single mapping change on TEWA-1000E with Tianyi_V1.0_JS2011; not for unrelated router models.
---

# Use ctgw

This Skill includes its complete Python CLI. Treat gateways as production network equipment.

## Prepare

1. Resolve this Skill's absolute directory. Use `uv run <skill>/scripts/ctgw.py` as the command prefix; no checkout, Go compiler, architecture-specific executable or PATH installation is required. Python 3.10+ is required. If Python and `keyring` are already available, `python <skill>/scripts/ctgw.py` also works. Dependency bootstrap may need Internet; read-only environment-credential calls and local diagnostics can run without keyring.
2. Run `... help`, `... version` and `... --json doctor`. Doctor is local and does not contact the gateway or read stored passwords.
3. Establish the authorized target from the current conversation. Supported model/firmware: **TEWA-1000E / Tianyi_V1.0_JS2011**. Do not assume support for a separate PPPoE router (including TP-Link SAR205GP-CM).
4. Run `... auth status` to check existing credentials internally. Use saved credentials, an existing secure process environment, or `--password-stdin`. Never ask for passwords in chat or print a keyring secret. Login and native keyring migration details are in [references/commands.md](references/commands.md).
5. Put global flags before commands; prefer `--json` for parsing.

Read [references/commands.md](references/commands.md) for exact flags, credential precedence, outputs and failure handling.

## Inspect

Start with the narrowest relevant read:

```text
<prefix> --json status
<prefix> --json info
<prefix> --json devices
<prefix> --json port list
```

Do not use `info --show-sensitive` unless those fields are specifically needed. Device lists, internal IPs and rule names can still be private; report only necessary findings.

## Change

Use the user's existing authorization; do not request the same permission again. Do not infer authorization for unrelated writes from a read request.

1. Inspect immediately before changing a mapping. Identify one exact rule or complete new rule and preserve a verified recovery path.
2. Execute the exact mutation with `--yes`. No bulk, wildcard, implicit replacement or speculative live write tests.
3. The CLI reads back the target and unrelated mappings before reporting verified success. A failed/uncertain submission must not be replayed automatically. Run `port list` to resolve actual state first; do not invent rollback commands.
4. Report the intended change and verified result without exposing unrelated data.

For an authorized reboot, establish the expected outage and recovery path, then run `reboot --yes`. A request receipt does not prove recovery: re-read gateway status and verify Internet reachability separately.

## Limits

- Python migration tests use a synthetic gateway and injected credential stores; native keyrings and real device writes are not established by passing CI.
- Every write requires `--yes`; keep credentials out of arguments, shell traces, generated files, raw tool output and public logs.
- Never extract a saved secret manually or copy profiles into reports.
- Only the stated model/firmware is supported. Similar endpoint names are not evidence of compatibility.
