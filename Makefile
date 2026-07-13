.PHONY: setup format format-check lint typecheck test shellcheck shfmt config-check version-check suppressions-check secrets verify

setup:
	pip install -r requirements-dev.txt
	command -v shellcheck >/dev/null 2>&1 || brew install shellcheck
	command -v shfmt >/dev/null 2>&1 || brew install shfmt
	command -v gitleaks >/dev/null 2>&1 || brew install gitleaks
	command -v lefthook >/dev/null 2>&1 || brew install lefthook
	@lefthook install || echo "NOTICE: lefthook install did not wire .git/hooks (e.g. a custom core.hooksPath) — see lefthook.yml"

format:
	ruff format .

format-check:
	ruff format --check .

lint:
	ruff check .

typecheck:
	pyright

test:
	pytest

shellcheck:
	shellcheck install.sh uninstall.sh tools/*.sh .claude/hooks/*.sh

shfmt:
	shfmt -d -i 2 install.sh uninstall.sh tools/*.sh .claude/hooks/*.sh

config-check:
	bash tools/check-config.sh

version-check:
	bash tools/check-version.sh

suppressions-check:
	bash tools/check-suppressions.sh

secrets:
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect --no-banner --redact; \
	else \
		echo "NOTICE: gitleaks not found on PATH — skipping secrets scan"; \
	fi

verify: format-check lint typecheck test shellcheck shfmt config-check version-check suppressions-check secrets
