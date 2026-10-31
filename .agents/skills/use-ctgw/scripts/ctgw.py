# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring>=25,<27"]
# ///
"""Self-contained Agent Skill entrypoint; uv manages optional runtime setup."""

from ctgw.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
