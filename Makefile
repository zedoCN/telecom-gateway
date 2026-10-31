.PHONY: build test check skill

build:
	python3 -m build

test:
	PYTHONPATH=.agents/skills/use-ctgw/scripts python3 -m unittest discover -s tests -v

check: test
	git diff --check

skill:
	python3 scripts/skill_bundle.py pack
