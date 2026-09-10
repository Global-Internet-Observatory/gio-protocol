# gio-protocol

Protocol definitions for the Global Internet Observatory (GIO).

`gio-protocol` is the canonical source of truth for GIO's Protocol Buffers schemas. This repository intentionally contains protocol definitions only: no generated SDKs, no language-specific bindings, and no runtime implementation code.

## Repository scope

- Define versioned Protocol Buffers schemas under `proto/`.
- Enforce formatting, linting, compilation, and backward-compatibility checks with Buf.
- Version protocol changes through Git commits and tags.
- Keep code generation and language-specific integration in consumer repositories for now.

## Layout

```text
.
├── proto/                  # Canonical .proto sources
├── .github/workflows/      # CI
├── buf.yaml                # Buf module, lint, and breaking rules
├── Makefile                # Stable local task entrypoints
├── COMPATIBILITY.md        # Protocol evolution rules
├── CONTRIBUTING.md         # Contribution workflow
└── CHANGELOG.md            # Release notes
```

## Prerequisites

Install [Buf](https://buf.build/docs/installation/).

## Development

Run the complete local validation suite:

```bash
make check
```

Individual checks are also available:

```bash
make format
make format-check
make lint
make build
make breaking
```

`make breaking` compares the current schema against the `main` branch.

## Versioning

Protocol API major versions are encoded in protobuf package names such as `gio.<domain>.v1`. Repository releases are versioned separately with Git tags.

See [COMPATIBILITY.md](COMPATIBILITY.md) for the compatibility contract.
