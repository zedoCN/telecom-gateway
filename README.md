# Telecom Gateway CLI

[简体中文](README-zh-cn.md) | English

`ctgw` is an experimental, open-source command-line client for selected China Telecom residential gateways. It replaces an older Java/Kotlin API and browser-based manager with one small Go binary and an importable Go package.

The project currently targets the LuCI-style CGI interface observed on a **TEWA-1000E** running **Tianyi_V1.0_JS2011**. Other models and firmware versions may expose different authentication, fields, or write behavior. Compatibility claims must be backed by redacted fixtures and hardware verification.

Verified on that model and firmware: login, system-keyring credential reuse, status, default-redacted gateway information, and port-mapping list. Live write operations remain deliberately excluded from routine verification.

## Features

- Read gateway health, WAN/LAN information, connected devices, and port mappings.
- Add, enable, disable, or delete one exact port mapping.
- Request a gateway reboot.
- Produce human-readable tables or structured JSON.
- Hide MAC addresses, serial numbers, SSIDs, and WAN account names from `info` output by default.
- Require `--yes` for every mutating command.
- Reject implicit same-name replacement and verify port-mapping writes by reading the list back.
- Store a verified password in the current OS user's system keyring.
- Bundle Agent instructions and a reusable `ctgw` operation Skill.

There is deliberately no Web UI or background daemon.

## Install

Go 1.22 or newer is required when building from source.

```bash
go install github.com/zedoCN/telecom-gateway/cmd/ctgw@latest
```

From a clone:

```bash
make build
./bin/ctgw version
```

Until the GitHub repository and first release exist, use the local build command.

## Authentication

Global flags must appear before the command. The default gateway URL is `http://192.168.1.1`.

Store credentials once for the current OS user:

```bash
ctgw --username useradmin --password-stdin auth login
ctgw auth status
ctgw status
```

`auth login` verifies the credentials against the gateway before saving them. The password goes to macOS Keychain, Windows Credential Manager, or the Linux Secret Service; only the URL and username are written to the current user's configuration directory. Remove both with:

```bash
ctgw auth logout
```

Linux and BSD desktop users need an available Secret Service login collection. One-off and unattended use can still supply `CTGW_URL`, `CTGW_USERNAME`, and `CTGW_PASSWORD`; explicit flags and environment values override the stored profile.

Do not place passwords directly in command arguments, repository files, issue reports, CI logs, or shell history.

## Usage

Start with read-only commands:

```bash
ctgw --username useradmin --password-stdin status
ctgw --username useradmin --password-stdin info
ctgw --username useradmin --password-stdin devices
ctgw --username useradmin --password-stdin port list
```

Use `--json` before the command for machine-readable output:

```bash
ctgw --json --username useradmin --password-stdin port list
```

Sensitive gateway identifiers remain omitted unless explicitly requested:

```bash
ctgw --username useradmin --password-stdin info --show-sensitive
```

The CLI inspects the current mapping list before and after a change, rejects implicit same-name replacement, and verifies the read-back. Every write requires `--yes`:

```bash
ctgw port add \
  --name example-game \
  --client 192.0.2.10 \
  --protocol UDP \
  --external-port 8211 \
  --internal-port 8211 \
  --yes

ctgw port disable --name example-game --yes
ctgw port enable --name example-game --yes
ctgw port delete --name example-game --yes
ctgw reboot --yes
```

The examples use documentation-only addresses. Supply authentication with global flags or environment variables. Run `ctgw help` for the complete command surface.

## Agent use

The repository is designed for Agent-assisted development:

- [`AGENTS.md`](AGENTS.md) defines repository boundaries and validation rules.
- [`.agents/skills/develop-telecom-gateway/SKILL.md`](.agents/skills/develop-telecom-gateway/SKILL.md) guides implementation work.
- [`.agents/skills/use-ctgw/SKILL.md`](.agents/skills/use-ctgw/SKILL.md) guides safe operation of the CLI.

To make the operation Skill available to a personal Codex installation, copy the entire `use-ctgw` directory into `${CODEX_HOME:-$HOME/.codex}/skills/`, then invoke `$use-ctgw`.

## Development

```bash
make check
```

Tests use `httptest` and synthetic documentation addresses. Do not add live credentials, cookies, tokens, full gateway exports, WAN account names, MAC addresses, serial numbers, or SSIDs to fixtures.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before submitting changes.

## License

[MIT](LICENSE)
