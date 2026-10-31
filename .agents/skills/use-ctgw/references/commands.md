# ctgw commands

Prefix commands with `uv run <absolute-skill-path>/scripts/ctgw.py`, or use an installed `ctgw` console command. Examples below use `ctgw` as shorthand. Python 3.10+ is required. Script metadata installs `keyring>=25,<27` through uv. With Python and dependencies available, direct Python invocation also works.

```text
ctgw [--url URL] [--username NAME] [--password-stdin] [--json] [--timeout 15s] COMMAND
ctgw help
ctgw version
ctgw --json doctor
```

Doctor is local and reports runtime, dependency version, profile path and supported hardware, without checking native keyring availability or contacting a gateway. Timeout accepts positive seconds or units (`250ms`, `1m30s`); OS DNS lookup may exceed the socket I/O budget. Redirects are rejected; response bodies are limited to 8 MiB. Standard proxy environment settings apply; configure `NO_PROXY` for private targets as appropriate.

## Credentials

```text
ctgw --url http://192.0.2.1 --username NAME --password-stdin auth login
ctgw --json auth status
ctgw --json auth logout
```

Obtain stdin from an existing secure source or a local user input flow; do not generate a command containing a password literal or request it in chat. Login verifies gateway authentication before saving. Status/logout are local; logout deletes stored credentials, not the gateway session. Only URL and username are stored in the profile.

Selection: explicit URL/username flags > `CTGW_URL`/`CTGW_USERNAME` > profile > default URL `http://192.168.1.1`. Password stdin > `CTGW_PASSWORD` > saved password only when URL and username match. Login requires a fresh stdin/environment password. Malformed stored profiles cause an error; do not overwrite them speculatively.

Native stores: macOS Keychain, Windows Credential Manager, Linux Secret Service (available login collection and D-Bus). There is no plaintext fallback. Headless sessions may use process credentials. POSIX profile mode is 0600 in a 0700 directory; Windows uses inherited user ACLs. Paths are `~/Library/Application Support/ctgw/profile.json` on macOS, `%APPDATA%/ctgw/profile.json` on Windows, and `$XDG_CONFIG_HOME/ctgw/profile.json` or `~/.config/ctgw/profile.json` on Linux.

Go migration: macOS encoded values and Linux attributes are supported in synthetic tests. Windows must re-run `auth login`; the native representation differs, and Python logout does not delete the old Go Windows entry. Do not claim native migration verified from these tests.

## Read

```text
ctgw --json status
ctgw --json info
ctgw --json info --show-sensitive
ctgw --json devices
ctgw --json port list
```

Default info removes MAC, serial number, SSIDs and WAN account from both output formats. Device lists and mappings still include private data.

## Change

```text
ctgw --json port add --name NAME --client IP --protocol TCP|UDP|BOTH --external-port PORT --internal-port PORT --yes
ctgw --json port enable --name NAME --yes
ctgw --json port disable --name NAME --yes
ctgw --json port delete --name NAME --yes
ctgw --json reboot --yes
```

Exact mapping changes require complete, unambiguous snapshots. Duplicate add and missing target fail; enable/disable in the desired state is a no-op. CLI read-back verifies the target and unchanged unrelated mappings. There is no retry or rollback. If a write or read-back fails, inspect state before another write. Reboot only reports the request, so separately verify recovery and Internet connectivity.

## Output

Read JSON retains Go field names. All successful commands except help support `--json`:

- Mapping: `{"action":"port disable","name":"demo","changed":true,"verified":true}`. An idempotent no-op has `changed:false`.
- Reboot: `{"action":"reboot","requested":true}`.
- Login: `{"verified":true,"stored":true}`.
- No saved profile or successful logout: `{"stored":false}`.
- Saved auth status: URL, username and `password_storage:"system-keyring"`; never the password.

Exit 0 means success, 1 operational failure or uncertain result, 2 usage/missing credentials, 130 interrupt. Errors are plain stderr, even with `--json`, and never include raw gateway bodies. Do not equate an HTTP response or reboot receipt with verified recovery.
