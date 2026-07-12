# ctgw command reference

Place global flags before the command:

```text
ctgw [--url URL] [--username NAME] [--password-stdin] [--json] [--timeout DURATION] COMMAND
```

Environment alternatives are `CTGW_URL`, `CTGW_USERNAME`, and `CTGW_PASSWORD`. Never place password literals in command arguments.

## Read-only commands

```text
ctgw status
ctgw info
ctgw info --show-sensitive
ctgw devices
ctgw port list
```

`info` omits MAC, serial number, SSIDs, and WAN account by default. `--json` changes presentation but does not disable this redaction.

## Mutating commands

Every mutation requires `--yes`:

```text
ctgw port add --name NAME --client IP --protocol TCP|UDP|BOTH --external-port PORT --internal-port PORT --yes
ctgw port enable --name NAME --yes
ctgw port disable --name NAME --yes
ctgw port delete --name NAME --yes
ctgw reboot --yes
```

The CLI performs its own before/after read-back for mutations. Still read `ctgw port list` when planning and reporting a change. Use an exact rule name; do not derive or execute bulk operations.

## Output and exit behavior

- Exit `0`: command completed successfully.
- Exit `1`: gateway, authentication, protocol, or operation failure.
- Exit `2`: local usage or missing-credential error.
- `--json`: emit structured JSON for read-only commands.
- Human tables and JSON may contain internal IPs and device names; minimize what is copied into reports.
