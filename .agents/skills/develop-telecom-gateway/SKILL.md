---
name: develop-telecom-gateway
description: Develop, review, test, and document the open-source Telecom Gateway Go repository and its ctgw CLI. Use when Codex changes gateway protocol handling, authentication, response models, CLI commands or output, safety gates, tests, releases, compatibility documentation, or bundled Agent Skills in this repository.
---

# Develop Telecom Gateway

Build a small, auditable CLI and Go library for authorized management of supported residential gateways.

## Workflow

1. Read the root `AGENTS.md` and the relevant code and tests.
2. Identify whether the change belongs to protocol behavior in `gateway/` or command behavior in `internal/cli/`.
3. Reproduce protocol cases with `httptest` and synthetic documentation addresses.
4. Implement the smallest compatible change.
5. Update both user READMEs when commands, flags, compatibility, or security behavior changes.
6. Run `gofmt`, `go test ./...`, `go vet ./...`, and `git diff --check`.
7. Validate every changed folder below `.agents/skills/` with the Skill validator.

## Architecture boundaries

- Keep HTTP, authentication, response parsing, validation, and exported models in `gateway/`.
- Keep flags, environment variables, confirmation gates, exit codes, tables, and JSON presentation in `internal/cli/`.
- Keep `cmd/ctgw/` limited to process wiring and build-time version injection.
- Keep profile metadata and OS keyring access in `internal/credentials/`; never add a plaintext password fallback.
- Do not add a Web UI or daemon unless project scope is explicitly changed.
- Prefer the standard library and keep the binary easy to cross-compile.

## Protocol work

- Treat current compatibility as model-and-firmware specific.
- Add redacted fixtures for every new response shape.
- Do not infer write success from an HTTP status alone when the device exposes a verifiable read-back.
- Return concise errors without embedding response bodies that may contain sensitive data.
- Keep response size and request timeout limits.

## Safety and public-source hygiene

- Never add real credentials, session material, WAN accounts, MAC addresses, serial numbers, SSIDs, public IP snapshots, or full device exports.
- Preserve explicit `--yes` gates for every mutation.
- Keep destructive operations scoped to one exact object and exclude bulk operations.
- Keep sensitive `info` fields opt-in and redact them from default JSON as well as tables.
- Test credential flows through injected stores; ordinary tests must not touch the developer's real OS keyring or user profile.
- Do not contact a live gateway during ordinary tests.

## Public compatibility

- Treat exported Go symbols, commands, flags, environment variables, JSON shapes, and exit behavior as public API.
- Prefer additive changes and document intentional breaks in both language READMEs.
- Keep English and Simplified Chinese examples behaviorally identical.
