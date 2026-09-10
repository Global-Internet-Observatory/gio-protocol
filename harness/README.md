# Protocol conformance harness

This directory contains repository-internal tests for the GIO wire contract. It
is not an SDK, generated bindings are not committed, and runtime components must
not depend on anything under `harness/`.

The initial harness uses Buf's dynamic message support, so it does not generate
language bindings. Python is used only for fixture orchestration and semantic
checks and requires no third-party packages.

## Fixture layout

- `fixtures/valid/` contains messages that must decode and satisfy the protocol
  invariants.
- `fixtures/invalid/` contains structurally decodable messages that must fail at
  least one protocol invariant.

Fixtures use protobuf's canonical JSON mapping so changes remain readable in
code review. For each valid fixture, the harness converts JSON to protobuf wire
format, decodes it, encodes it again, and compares the decoded messages. It does
not require two semantically equivalent messages to have identical wire bytes.

Run the harness from the repository root:

```bash
make test
```

The `BUF` and `PYTHON` Make variables may select alternate executables.

## Adding fixtures

Add small, intentional examples by hand and run `make test`. Normal test runs
never rewrite committed fixtures. If golden binary fixtures become necessary,
their source message, deterministic-serialization requirement, regeneration
command, and review procedure must be documented beside them. Golden files must
never be regenerated silently by CI.

Semantic checks belong here only when they are part of the shared wire contract,
such as timestamp ordering and status/error/result relationships. Probe policy,
measurement scheduling, retries, and other runtime business rules do not.

Future coverage can add unknown-field preservation, enum evolution, optional
field presence, explicit `oneof` cases, and reviewed golden wire fixtures without
turning this directory into a consumer library.
