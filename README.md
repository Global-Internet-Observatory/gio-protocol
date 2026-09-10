# gio-protocol

`gio-protocol` defines the wire protocol of the **Global Internet Observatory (GIO)**.

GIO is a distributed Internet measurement system. Measurement nodes run observations from different networks and geographic locations, while ingestion and control-plane components collect, transport, interpret, and coordinate those measurements. These components may be implemented in different languages and released independently, so they need a small, stable, implementation-neutral contract.

This repository is that contract.

The Protocol Buffers definitions under `proto/` are the canonical source of truth for data exchanged between GIO components. In particular, this repository defines measurement records and the shared protocol types required by the GIO measurement pipeline.

## What belongs here

`gio-protocol` is intentionally a **schema-only repository**.

It is responsible for:

- defining versioned Protocol Buffers schemas;
- assigning stable field numbers, enum values, package names, and message semantics;
- documenting protocol-level semantics shared by independent implementations;
- validating schema formatting, lint rules, compilation, and backward compatibility with Buf;
- providing Git commits and tags that consumers can pin as protocol versions.

It is not responsible for:

- measurement execution or probe logic;
- collectors, ingestion services, schedulers, or control-plane implementation;
- database schemas or internal persistence models;
- generated Python, Rust, or other language bindings;
- SDK packaging or publication;
- application-specific convenience models that do not cross a protocol boundary.

For now, consumer repositories generate their own language bindings from a pinned revision of this repository. Generated code must not be committed here.

## Role in GIO

The protocol sits below the runtime components of GIO:

```text
                      gio-protocol
                    Protocol Buffers
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
       probes          ingestion      control plane
          │               │               │
          └──────── measurement pipeline ──┘
```

A protocol change must therefore be treated differently from an ordinary implementation change. Once a field or message is used by deployed components or persisted measurement data, its wire identity and semantics become part of the long-lived GIO contract.

## Design principles

Protocol development follows a few core principles:

1. **The wire contract is implementation-neutral.** Schemas describe exchanged data, not Python classes, Rust structs, database tables, or internal service architecture.
2. **Compatibility is the default.** Existing versioned packages evolve additively whenever possible. Field numbers and enum numeric values are never repurposed.
3. **Semantics matter as much as wire compatibility.** A change that still parses but changes the meaning of an existing field is a breaking protocol change.
4. **Measurements must remain interpretable over time.** GIO may retain measurements longer than the lifetime of the software that produced them, so historical data must not depend on transient implementation details.
5. **Protocol surface area stays small.** A type belongs here only when independent GIO components need to agree on it.

The enforceable compatibility policy is documented in [COMPATIBILITY.md](COMPATIBILITY.md).

## Repository layout

```text
.
├── proto/                  # Canonical .proto sources
├── .github/workflows/      # Protocol CI
├── buf.yaml                # Buf module, lint, and breaking rules
├── Makefile                # Stable local development entrypoints
├── COMPATIBILITY.md        # Protocol evolution rules
├── CONTRIBUTING.md         # Contribution and review workflow
└── CHANGELOG.md            # Release notes
```

Protocol files live under `proto/` and use versioned protobuf packages such as:

```protobuf
package gio.<domain>.v1;
```

Package versions are protocol API major versions. They are not the same thing as repository release tags.

## Development prerequisites

Install [Buf](https://buf.build/docs/installation/) and GNU Make or a compatible `make` implementation.

No Python, Rust, `protoc`, SDK toolchain, or Buf Schema Registry account is required to develop the schemas in this repository.

## Development workflow

Protocol development should follow the same lifecycle whether a change introduces a new measurement type or extends an existing message.

### 1. Start from the protocol boundary

Before editing a `.proto` file, determine whether the concept actually needs to cross an independent component boundary.

If a value is only needed inside one probe, service, database, or implementation, keep it in that repository. Add it to `gio-protocol` only when multiple components must agree on its serialized representation or semantics.

### 2. Prefer compatible evolution

Compatible additions belong in the current versioned package, for example `gio.<domain>.v1`.

Do not create `v2` merely because a message gained a field. A new major package version is reserved for changes that cannot be represented while preserving the existing compatibility contract.

### 3. Edit schemas conservatively

When changing an existing message:

- add new fields with new field numbers;
- never renumber an existing field;
- never reuse a removed field number or name;
- preserve enum numeric values;
- reserve removed field numbers and names;
- avoid changing the documented meaning of an existing field;
- prefer explicit protocol semantics over implementation-specific shortcuts.

See [COMPATIBILITY.md](COMPATIBILITY.md) before making any non-additive change.

### 4. Format and validate locally

Format changed schemas:

```bash
make format
```

Run the complete local validation suite:

```bash
make check
```

The stable task entrypoints are:

```bash
make format        # Rewrite .proto files using Buf formatting
make format-check  # Verify formatting without modifying files
make lint          # Run Buf lint rules
make build         # Compile and validate the schema graph
make breaking      # Compare against main when a schema baseline exists
make check         # Run the complete validation suite
```

During the initial repository bootstrap, when no `.proto` files exist yet, schema checks intentionally succeed without running Buf against an empty module. The first schema can therefore establish the compatibility baseline. After that schema reaches `main`, breaking-change checks become part of every subsequent protocol PR.

### 5. Open a focused pull request

A protocol PR should explain the **semantic contract**, not only the syntax change. Reviewers should be able to determine:

- what new information is being represented;
- which components are expected to produce and consume it;
- whether old producers can communicate with new consumers and vice versa;
- whether persisted historical measurements retain their original meaning;
- why the change belongs in the shared protocol rather than one implementation.

CI verifies formatting, linting, schema compilation, and, once a baseline exists, breaking compatibility against the target branch.

### 6. Update consumers explicitly

Merging a schema change does not automatically update runtime components.

Each consumer repository should pin the desired `gio-protocol` commit or release and regenerate its own language bindings using its local toolchain. This keeps code generation out of the protocol repository while making the exact protocol revision used by each component explicit.

### 7. Release deliberately

Repository releases are identified by Git tags. A release tag describes one coherent revision of the complete protocol repository.

Protocol package versions and repository release versions are separate concepts. For example, a future repository release may contain both `gio.foo.v1` and `gio.bar.v2` packages.

Release notes should be recorded in [CHANGELOG.md](CHANGELOG.md), with particular attention to new fields, messages, enum values, deprecations, and migration implications for consumers.

## Continuous protocol evolution

The expected long-term development model is additive evolution rather than periodic schema replacement:

```text
initial v1 schema
      │
      ├── add compatible fields
      ├── add messages and enums
      ├── reserve retired fields
      ├── refine documentation without changing semantics
      │
      └── continue within v1

only an unavoidable incompatible redesign
      │
      └── introduce a new ...v2 package alongside v1
```

Old package versions are not immediately removed when a new major version appears. Multiple major protocol packages may coexist while deployed GIO components migrate independently.

This matters especially for a globally distributed measurement system: probes, ingestion infrastructure, and control-plane services will not always upgrade atomically.

## Versioning and compatibility

There are two independent version axes:

- **Protocol API major version** — encoded in protobuf packages, for example `gio.<domain>.v1`.
- **Repository release version** — represented by Git tags and used to identify a complete revision of this repository.

Within an existing protocol major version, backward-compatible evolution is required. Buf uses the `FILE` breaking-change policy as an automated guard, while [COMPATIBILITY.md](COMPATIBILITY.md) defines the stronger semantic rules that automated checks cannot fully enforce.

## Current project stage

`gio-protocol` is currently establishing the first version of the GIO measurement protocol. The repository deliberately does not publish SDKs or generated language packages yet. That can be added later if repeated consumer-side code generation becomes sufficiently costly to justify a separate SDK distribution layer.

Until then, keep this repository focused on one thing: a precise, durable, language-independent contract for the Global Internet Observatory.
