---
name: develop-telecom-gateway
description: Develop, review, test and document the Python Telecom Gateway repository, ctgw CLI and self-contained Agent Skill. Use for protocol/authentication handling, response models, credentials, CLI behavior, verified writes, packaging, CI and compatibility documentation.
---

# Develop Telecom Gateway

Read root AGENTS.md and both READMEs. Main is Python; Go history is preserved on branch `go`.

## Workflow

1. Inspect the relevant canonical code in `.agents/skills/use-ctgw/scripts/ctgw/` and tests in `tests/`.
2. Reproduce protocol behavior with a localhost synthetic HTTP server. Inject fake credentials; never contact a real gateway or native keyring during ordinary tests.
3. Keep HTTP/session behavior in client.py, schema validation in models.py, native secrets/profile handling in credentials.py, and CLI/confirmation/redaction/read-back in cli.py.
4. Implement the smallest change. Prefer standard library; keyring exists specifically to avoid plaintext secrets. Do not add web UIs or daemons without a scope change.
5. Preserve exact writes, `--yes`, response/time limits, no redirects, no replay of uncertain writes, and sensitive output redaction. Add targeted tests for these boundaries when touched.
6. Keep both READMEs and the operation Skill aligned. Do not claim unsupported hardware or native keyring acceptance from mocks.
7. Run `python -m unittest discover -s tests -v` against canonical source. Build/install wheel and sdist for packaging changes; pack and extract the Skill to verify it runs outside the checkout.
8. Validate changed Skills with the host's Skill validator, run `git diff --check`, and inspect staged contents for sensitive values.

## Distribution

The Python package source lives inside the distributable operation Skill. Do not maintain a second runtime copy in this repo. `scripts/ctgw.py` has PEP 723 dependencies for uv. `pyproject.toml` exposes the console script; `scripts/skill_bundle.py` creates a deterministic ZIP with checksum or installs into an unused Skill target. Include license/references, exclude caches, binaries, profiles and credentials.

Treat existing CLI/JSON interfaces as public. Update both READMEs for intentional compatibility changes. The Go branch retains the original public Go API; main does not duplicate it.
