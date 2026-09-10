BUF ?= buf
PYTHON ?= python3
BREAKING_BASE ?= main
PROTO_FILES := $(shell find proto -type f -name '*.proto' -print -quit 2>/dev/null)

.PHONY: format format-check lint build breaking test check require-schema

require-schema:
	@if [ -z "$(PROTO_FILES)" ]; then \
		echo 'No .proto files yet; nothing to check.'; \
		exit 2; \
	fi

format:
	@if [ -z "$(PROTO_FILES)" ]; then echo 'No .proto files yet; nothing to format.'; else $(BUF) format -w; fi

format-check:
	@if [ -z "$(PROTO_FILES)" ]; then echo 'No .proto files yet; formatting check skipped.'; else $(BUF) format --diff --exit-code; fi

lint:
	@if [ -z "$(PROTO_FILES)" ]; then echo 'No .proto files yet; lint skipped.'; else $(BUF) lint; fi

build:
	@if [ -z "$(PROTO_FILES)" ]; then echo 'No .proto files yet; build skipped.'; else $(BUF) build; fi

breaking:
	@if [ -z "$(PROTO_FILES)" ]; then \
		echo 'No .proto files yet; breaking check skipped.'; \
	elif ! git rev-parse --verify '$(BREAKING_BASE)^{commit}' >/dev/null 2>&1 || \
		! git ls-tree -r --name-only '$(BREAKING_BASE)' -- proto | grep -q '\.proto$$'; then \
		echo 'The breaking-change baseline has no .proto files; check skipped.'; \
	else \
		$(BUF) breaking --against '.git#ref=$(BREAKING_BASE)'; \
	fi

test:
	@BUF='$(BUF)' $(PYTHON) harness/test_conformance.py

check: format-check lint build breaking test
