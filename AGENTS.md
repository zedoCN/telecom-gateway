# AGENTS.md

This repository contains `ctgw`, an open-source Go CLI and library for supported China Telecom residential gateways. Treat every reachable gateway as production network equipment.

## Start here

1. Read `README.md` and `README-zh-cn.md` for the public compatibility promise.
2. Use `$develop-telecom-gateway` for code, tests, command behavior, and documentation changes.
3. Use `$use-ctgw` when operating a real gateway through the CLI.
4. Inspect the current code and tests before changing protocol assumptions.

## Repository map

- `cmd/ctgw/`: executable entry point and build-time version.
- `internal/cli/`: command parsing, confirmation gates, and output formatting.
- `gateway/`: importable protocol client, response models, and synthetic tests.
- `.agents/skills/develop-telecom-gateway/`: repository development workflow.
- `.agents/skills/use-ctgw/`: distributable operation Skill.
- `README.md` and `README-zh-cn.md`: English and Simplified Chinese user documentation; keep behavior and examples aligned.

## Non-destructive rules

- Never commit or print passwords, cookies, tokens, WAN account names, full device exports, MAC addresses, serial numbers, SSIDs, or real public IP snapshots.
- Never run live gateway tests unless the user explicitly requests them and identifies the authorized target.
- Run read-only inspection before any live mutation and verify the exact affected object afterward.
- Keep every write operation narrow. Do not add bulk delete, bulk disable, bulk enable, or implicit replacement commands.
- Preserve `--yes` confirmation for mutations. Do not make write operations the default behavior of a command.
- Keep sensitive fields redacted by default. An explicit opt-in may reveal them locally, but tests, issues, and documentation must remain synthetic.
- Do not claim compatibility with a model or firmware based only on similar HTML, endpoint names, or third-party reports.

## Development workflow

1. Reproduce behavior with `httptest` and redacted fixtures.
2. Keep HTTP/session behavior in `gateway/`; keep presentation and shell semantics in `internal/cli/`.
3. Prefer the Go standard library. Add a dependency only when it removes meaningful complexity and document why.
4. Run `gofmt` on changed Go files.
5. Run `go test ./...` and `go vet ./...`.
6. Validate changed Skills with the repository's documented Skill validator.
7. Run `git diff --check` and inspect the staged diff for sensitive values before committing.

## Public API and CLI compatibility

- Treat exported symbols in `gateway/`, JSON field names, command names, flags, output fields, and exit behavior as public compatibility surfaces.
- Prefer additive changes. If a breaking change is necessary, update both READMEs and release notes.
- Global flags currently precede commands; examples must preserve that ordering.
- Human output may improve, but `--json` must remain stable enough for automation.

## Git

- Keep commits small and focused.
- Do not rewrite contributor history or force-push without explicit approval.
- Do not revert unrelated user changes.
