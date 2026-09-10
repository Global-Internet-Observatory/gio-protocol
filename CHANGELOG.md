# Changelog

All notable changes to `gio-protocol` will be documented in this file.

The project is currently pre-release. Release entries will be added when protocol versions are tagged.

## Unreleased

- Initialize the protocol-only repository structure.
- Add Buf formatting, linting, build, and breaking-change checks.
- Add compatibility and contribution policies.
- Add the initial `gio.common.v1` and `gio.measurement.v1` protocol schemas.
- Add typed DNS, HTTP, TCP connect, and TLS handshake measurement results.
- Add repository-internal wire and semantic conformance fixtures.
- Audit Measurement v1 semantics: explicit HTTP body capture and observed size,
  optional DNS response truncation, and a general error fallback.
- Document terminal states, partial HTTP results, timing, endpoint provenance,
  privacy, and unknown-field/enum compatibility expectations.
- Expand fixtures across all four measurement kinds and add binary evolution
  coverage, exact semantic-failure expectations, and nanosecond timestamp checks.
- Fail local breaking validation when its comparison baseline cannot be resolved.
