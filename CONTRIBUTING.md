# Contributing

Read AGENTS.md and `.agents/skills/develop-telecom-gateway/SKILL.md`. Main uses Python 3.10+; the original Go implementation remains on `go`.

Install with `python -m pip install -e .`, then run `python -m unittest discover -s tests -v` and `git diff --check`. Packaging changes also require wheel/sdist installation and an extracted Skill smoke test. CI checks Linux, macOS and Windows without live hardware or native credentials.

Use synthetic fixtures and injected stores. Never publish real credentials, cookies, tokens, identifiers or raw device exports. Keep writes exact, confirmed and verified; document public changes in both READMEs. Report vulnerabilities through the private process in SECURITY.md.
