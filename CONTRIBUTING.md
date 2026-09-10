# Contributing

## Principles

`gio-protocol` is a protocol-definition repository. Keep runtime code, generated bindings, SDKs, and implementation-specific behavior out of this repository unless that scope is explicitly changed later.

## Workflow

1. Create a topic branch from `main`.
2. Edit protobuf schemas under `proto/`.
3. Add or update conformance fixtures when protocol behavior changes.
4. Run `make format`.
5. Run `make check`.
6. Open a pull request describing both wire-level and semantic effects.

## Schema changes

Every schema change should answer:

- Is it backward compatible with already stored and transmitted data?
- Can older consumers safely receive messages produced by newer components?
- Does the change alter field semantics, units, cardinality, or lifecycle?
- Does a removed field reserve both its name and number?
- Does the change belong in the existing protobuf API major version?

See `COMPATIBILITY.md` for the normative compatibility policy.

## Conformance harness

The harness under `harness/` tests the shared protocol contract without exposing
a consumer API. Keep its fixtures small and reviewable. Add semantic checks only
for invariants every conforming implementation must enforce; runtime policy and
business validation belong in runtime repositories.

The harness may use temporary generated artifacts, but they must remain outside
`proto/`, must not be committed or published, and must never become a dependency
of GIO components. See `harness/README.md` for fixture conventions.

## Generated code

Do not commit generated language bindings to this repository. Consumers are responsible for code generation until GIO explicitly introduces SDK distribution.

## Commit and pull request scope

Prefer small protocol changes with a single semantic purpose. Avoid combining unrelated schema evolution, repository tooling changes, and consumer implementation changes in one pull request.
