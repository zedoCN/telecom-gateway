# Telecom Gateway

[简体中文](README-zh-cn.md)

`ctgw` is a Python CLI and self-contained Agent Skill for authorized management of a **China Telecom TEWA-1000E running Tianyi_V1.0_JS2011**. Similar web interfaces do not establish support for other hardware; TP-Link SAR205GP-CM is not supported.

`main` contains Python + Agent Skill. The original Go CLI/library is preserved on the [`go` branch](https://github.com/zedoCN/telecom-gateway/tree/go), starting at `e5058897d24e8d335c84248ff57e5022a0bc2deb`. Go users can use `go install github.com/zedoCN/telecom-gateway/cmd/ctgw@go`; main no longer provides the Go library.

## Install

Requires Python 3.10+. Install the CLI with [uv](https://docs.astral.sh/uv/) or pip in a virtual environment:

```sh
uv tool install 'git+https://github.com/zedoCN/telecom-gateway.git@main'
ctgw help
ctgw --json doctor
```

From a checkout, `python -m pip install .` installs the same package. No PyPI release is currently required for these commands.

### Agent Skill

Install the entire `.agents/skills/use-ctgw` directory with an Agent Skill installer, or from a checkout:

```sh
python scripts/skill_bundle.py install
# For Codex's alternate Skill root:
python scripts/skill_bundle.py install --destination ~/.codex/skills
python scripts/skill_bundle.py pack --output dist/use-ctgw.zip
```

The installer refuses existing targets, including symlinks. Update through the existing installation's owner rather than overwriting it. The ZIP includes a SHA-256 sidecar and contains the Skill, Python runtime source, references and MIT license. It needs neither a Go compiler nor an architecture-specific executable or PATH change.

An installed Skill runs independently of this checkout:

```sh
uv run /absolute/path/use-ctgw/scripts/ctgw.py --json doctor
```

`uv` reads the script's dependency metadata. With Python and `keyring` already installed, `python /absolute/path/use-ctgw/scripts/ctgw.py ...` also works. Local help/version/doctor and environment-only gateway access do not require loading a keyring backend. The ZIP includes source, not Python or dependency wheels; dependency bootstrap may require Internet access.

## Credentials

Global flags precede the command:

```text
ctgw [--url URL] [--username NAME] [--password-stdin] [--json] [--timeout 15s] COMMAND
ctgw --username NAME --password-stdin auth login
ctgw auth status
ctgw auth logout
```

Supply passwords through an existing secure stdin source or process environment, never a literal argument or a public log. `auth login` verifies the gateway login before saving. `auth status` and `auth logout` manage local credentials without contacting the gateway. Flags override `CTGW_URL`/`CTGW_USERNAME`, which override the saved profile. Password stdin overrides `CTGW_PASSWORD`; the saved secret is used only for the same URL and username. Default URL is `http://192.168.1.1`.

Passwords stay in macOS Keychain, Windows Credential Manager, or Linux Secret Service (an available login collection and D-Bus session are needed). There is no plaintext fallback. Headless hosts can use process credentials instead. Profiles store only URL and username at:

- macOS: `~/Library/Application Support/ctgw/profile.json`
- Windows: `%APPDATA%/ctgw/profile.json`
- Linux: `$XDG_CONFIG_HOME/ctgw/profile.json`, otherwise `~/.config/ctgw/profile.json`

POSIX profile directories/files use 0700/0600; Windows relies on the user's inherited ACLs. Existing Go macOS encoded secrets and Linux account attributes are supported by synthetic compatibility tests; native migration has not been exercised on every OS. **Windows users migrating from Go must run `auth login` again**, because the native credential representation differs. Python `auth logout` does not remove the old Go Windows entry.

## Inspect and change

```sh
ctgw --json status
ctgw --json info
ctgw --json devices
ctgw --json port list
ctgw --json port add --name demo --client 192.0.2.10 --protocol TCP --external-port 8443 --internal-port 443 --yes
ctgw --json port disable --name demo --yes
ctgw --json port enable --name demo --yes
ctgw --json port delete --name demo --yes
ctgw --json reboot --yes
```

Inspect first and keep a recovery path. Every gateway write requires `--yes`. Mapping changes affect one exact name, reject duplicate/ambiguous names or incomplete snapshots, and verify the target plus unrelated rules afterward. Already-enabled/disabled rules are successful no-ops. No bulk operation, implicit replacement, automatic retry or automatic rollback is provided. If a write times out or read-back fails, inspect state before deciding whether to retry. A reboot receipt means requested, not recovered; check gateway state and Internet reachability separately.

`info` redacts MAC, serial number, SSIDs and WAN account in both text and JSON; `info --show-sensitive` explicitly reveals known fields locally. Devices and mappings can still contain private network information.

Read command JSON retains Go field names. JSON now also covers local diagnostics/auth and mutations, for example `{"action":"port disable","name":"demo","changed":true,"verified":true}` or `{"action":"reboot","requested":true}`. Errors go to stderr without raw gateway bodies. Exit codes: 0 success, 1 operational failure/uncertain result, 2 usage/missing credentials, 130 interrupted. Human formatting can differ from Go.

`--timeout` accepts seconds or durations such as `250ms`, `15s`, `1m30s`. It bounds socket I/O across the command; OS DNS resolution can exceed that budget. Responses are size-limited and redirects are refused. Proxy environment variables follow Python's standard URL opener behavior; configure `NO_PROXY` appropriately for private gateways. HTTP gateways send credentials without transport encryption; operate only on trusted networks or a secure tunnel.

## Development and verification

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/skill_bundle.py pack
python -m pip install build
python -m build
```

Protocol/CLI tests use a localhost synthetic gateway; credential tests inject a fake store. Ordinary tests never access a real gateway or system keyring. CI exercises Python 3.10/3.13 on Linux, macOS and Windows, and builds the wheel, source and Skill bundles. This does not establish native keyring or real-device write acceptance. The Python migration has no new live-hardware acceptance claim; the original Go version had read-only verification on the stated model/firmware.

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and [LICENSE](LICENSE).
