# Changelog

All notable changes to `gio-protocol` will be documented in this file.

Repository releases are Git tags. Their versions are independent of the API
major versions in protobuf package names.

## Unreleased

No changes yet.

## 0.1.0 — 2026-09-10

First consumable GIO protocol source release, following the Measurement v1
semantic audit. Consumers pin the `v0.1.0` Git tag or its commit and generate
their own language bindings. The tag identifies the repository release;
`gio.measurement.v1` remains the protocol API major version.

- Include `gio.common.v1` probe/location/network context and IP endpoint types,
  and `gio.measurement.v1` targets, envelope, terminal statuses, and errors.
- Support DNS queries, HTTP transactions, TCP connection establishment, and TLS
  handshakes. Document success, failure, partial results, timing boundaries,
  target versus observed endpoint distinctions, and privacy-sensitive metadata.
- Distinguish complete, truncated, intentionally uncaptured, and unreported HTTP
  body capture; report optional observed body size and DNS response truncation.
  Include a general error fallback without OS/vendor-specific error values.
- Include an internal Buf/Python standard-library conformance harness with
  10 valid fixtures, 19 semantic-invalid fixtures, and 23 binary/evolution cases
  covering unknown fields/enums, optional presence, oneof decoding, and exact
  timestamp ordering. No generated language APIs are part of the harness.
- Preserve all schema field numbers and enum values allocated on `main`. Future
  v1 evolution must follow the additive and semantic rules in COMPATIBILITY.md,
  enforced by Buf's FILE breaking policy. Missing new metadata means unknown;
  future enum numbers are decodable but may require newer semantic understanding.
- Record the pre-release HTTP clarification: PARTIAL responses may omit the
  successful-completion elapsed time when body reception fails. Existing elapsed
  meaning is preserved; consumers should use the audited semantic rules.
- Provide formatting, lint, build, breaking, and harness validation through
  `make check`, with path-aware CI and the stable final `CI gate`. Unresolvable
  local breaking baselines fail instead of silently skipping.

The distribution unit is this Git repository/tag. SDKs, generated bindings,
Python packages, Rust crates, SDK archives, and BSR modules are not included.
Richer DNS sections, TLS pre-failure observations, redirect history, and new
measurement families are deferred.
