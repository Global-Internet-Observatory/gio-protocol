# Contributing

## Principles

`gio-protocol` is a protocol-definition repository. Keep runtime code, generated bindings, SDKs, and implementation-specific behavior out of this repository unless that scope is explicitly changed later.

## Workflow

1. Create a topic branch from `main`.
2. Edit protobuf schemas under `proto/`.
3. Run `make format`.
4. Run `make check`.
5. Open a pull request describing both wire-level and semantic effects.

## Schema changes

Every schema change should answer:

- Is it backward compatible with already stored and transmitted data?
- Can older consumers safely receive messages produced by newer components?
- Does the change alter field semantics, units, cardinality, or lifecycle?
- Does a removed field reserve both its name and number?
- Does the change belong in the existing protobuf API major version?

See `COMPATIBILITY.md` for the normative compatibility policy.

## Generated code

Do not commit generated language bindings to this repository. Consumers are responsible for code generation until GIO explicitly introduces SDK distribution.

## Commit and pull request scope

Prefer small protocol changes with a single semantic purpose. Avoid combining unrelated schema evolution, repository tooling changes, and consumer implementation changes in one pull request.
