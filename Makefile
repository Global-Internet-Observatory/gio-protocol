BUF ?= buf

.PHONY: format format-check lint build breaking check

format:
	$(BUF) format -w

format-check:
	$(BUF) format --diff --exit-code

lint:
	$(BUF) lint

build:
	$(BUF) build

breaking:
	$(BUF) breaking --against '.git#branch=main'

check: format-check lint build breaking
