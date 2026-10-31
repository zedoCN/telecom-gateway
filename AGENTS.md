# AGENTS.md

This repository contains the Python `ctgw` CLI and a self-contained Agent Skill. The original Go CLI/library lives on branch `go`. Treat reachable gateways as production equipment.

## Start and map

Read both READMEs for compatibility, then `.agents/skills/develop-telecom-gateway/SKILL.md` for development or `.agents/skills/use-ctgw/SKILL.md` for operation.

The single runtime source is `.agents/skills/use-ctgw/scripts/ctgw/`: `client.py` handles bounded HTTP/authentication, `models.py` validates responses, `credentials.py` owns profiles/native keyrings, and `cli.py` owns command semantics, redaction and verified changes. `scripts/ctgw.py` is the standalone PEP 723 entry; root packaging installs that same package. Tests live in `tests/`; `scripts/skill_bundle.py` distributes only approved Skill files.

## Boundaries

- Never commit or print credentials, cookies, tokens, full device exports or real device identifiers.
- Ordinary tests use localhost synthetic gateways and injected stores, never live devices or the developer's native keyring.
- Live operations require user authorization and an identified target. Inspect first, preserve recovery access, verify exact affected state.
- Preserve `--yes`, single exact mappings, redaction, bounded responses, no redirects and no automatic write retry. Never add bulk operations or implicit replacement.
- Keep Python standard library protocol/CLI; keyring is the sole runtime dependency for native secret storage. No plaintext fallback.
- Do not claim hardware/firmware compatibility or native keyring acceptance from CI alone.
- Preserve commands, flags, JSON keys and credential precedence; document intentional changes in both languages. Global flags precede commands; human formatting may change.

## Validation and delivery

Run `python -m unittest discover -s tests -v`, build/install wheel and source bundles when packaging changes, validate changed Skills and run `git diff --check`. Review staged files for secrets. Tests must not import an installed stale copy instead of the canonical source.

Use small focused commits. Do not force-push, rewrite history or modify unrelated work. New branches default to `codex/`. Go archive branch must retain the original implementation.
