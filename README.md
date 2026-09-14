# gio-protocol

`gio-protocol` defines the wire protocol of the **Global Internet Observatory (GIO)**.

GIO is a distributed Internet measurement system. Measurement nodes run observations from different networks and geographic locations, while ingestion and control-plane components collect, transport, interpret, and coordinate those measurements. These components may be implemented in different languages and released independently, so they need a small, stable, implementation-neutral contract.

This repository is that contract.

The Protocol Buffers definitions under `proto/` are the canonical source of truth for data exchanged between GIO components. In particular, this repository defines Measurement v1 records and the shared protocol types required by the GIO measurement pipeline.

## What belongs here

`gio-protocol` is intentionally a **protocol-only repository**.

It is responsible for:

- defining versioned Protocol Buffers schemas;
- assigning stable field numbers, enum values, package names, and message semantics;
- documenting protocol-level semantics shared by independent implementations;
- validating schema formatting, lint rules, compilation, and backward compatibility with Buf;
- maintaining repository-internal protocol conformance fixtures and tests;
- providing Git commits and tags that consumers can pin as protocol versions.

It is not responsible for:

- measurement execution or probe logic;
- collectors, ingestion services, schedulers, or control-plane implementation;
- database schemas or internal persistence models;
- generated Python, Rust, or other language bindings;
- SDK packaging or publication;
- application-specific convenience models that do not cross a protocol boundary.

For now, consumer repositories pin a Git revision and generate their own language bindings. They must not depend on harness code or harness-generated artifacts. Generated code must not be committed here.

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

## Measurement v1

Measurement v1 is the first concrete GIO wire contract. It uses an extensible
`gio.measurement.v1.Measurement` envelope containing measurement identity,
timing, probe and network context, target information, terminal execution
status, structured errors, and one typed result.

The initial typed results cover DNS queries, HTTP transactions, TCP connection
attempts, and TLS handshakes. A separate `kind` remains present even when a
failed measurement has no result, so consumers can always interpret what was
attempted. New result variants can be added compatibly to the envelope's
`oneof`; existing field numbers and meanings remain permanent.

Types shared outside the measurement domain, such as IP endpoints and probe or
network context, live in `gio.common.v1`. Measurement targets and result payloads
remain in `gio.measurement.v1`. The schemas define no RPC services.

The [Measurement v1 contract](proto/gio/measurement/v1/README.md) explains terminal
statuses, partial observations, target versus observed endpoints, timing, privacy,
and forward compatibility. HTTP results distinguish complete, truncated, and
intentionally uncaptured bodies; omitted capture metadata means unknown.

## Ingestion v1

The current production data-plane stack is:

```text
Measurement v1 -> Ingestion v1 -> Ingestion Authentication v1
```

Authentication v1 binds an authenticated transport principal to
`Measurement.probe.probe_id` while leaving both protobuf contracts unchanged.

Ingestion v1 is the transfer and durability boundary for a future collector. A
probe sends the exact serialized Measurement v1 bytes in an
`gio.ingestion.v1.MeasurementUpload`, alongside the logical `measurement_id` and
the SHA-256 of those exact bytes:

```text
Measurement v1 -> exact bytes -> ingestion request -> durable ownership -> ACK
```

Only an acknowledgement with a matching ID, matching 32-byte SHA-256, and
`STORED` or `ALREADY_STORED`, received over authenticated HTTPS server transport
and an authenticated request principal bound to the Measurement's `probe_id`,
permits a probe to remove its local copy. The digest binds the ACK to exact
bytes; TLS authenticates its transport origin. Delivery is at-least-once;
duplicate submissions are normal, server deduplication is required, and global
ordering is not promised. `RETRY` and `REJECTED` never authorize deletion, and
`REJECTED` must not cause silent data loss. The
[Ingestion v1 contract](proto/gio/ingestion/v1/README.md), its
[HTTP transport profile](proto/gio/ingestion/v1/HTTP.md), and
[Ingestion Authentication v1](proto/gio/ingestion/v1/AUTHENTICATION.md) define
these rules.

Collector implementation, credential issuance, production storage, scheduling,
and runtime registration implementation remain deferred. The first control-plane
contract, Probe Registration v1, now defines only identity and initial
credential binding; its [contract](proto/gio/control/v1/README.md) and
[HTTP profile](proto/gio/control/v1/HTTP.md) do not define a service.

## Probe Registration v1

`gio.control.v1` consumes a one-time enrollment credential at
`POST /v1/probes:register`. A probe generates and durably persists its opaque
`registration_id`, control bearer token, and ingestion bearer token before the
first request. The control plane assigns `probe_id`, stores protected verifiers,
and returns only the correlated registration ID and assigned probe ID. Exact
retries are idempotent, including after response loss; changed credentials and
registration collisions are conflicts. Task Lease, heartbeat, scheduling,
capabilities, credential rotation, enrollment issuance, and runtime code are
deferred.

This is a credential provisioning-origin clarification for Authentication v1;
it changes no Authentication HTTP behavior. There is no Measurement or
Ingestion protobuf change.

## Design principles

Protocol development follows a few core principles:

1. **The wire contract is implementation-neutral.** Schemas describe exchanged data, not Python classes, Rust structs, database tables, or internal service architecture.
2. **Compatibility is the default.** Existing versioned packages evolve additively whenever possible. Field numbers and enum numeric values are never repurposed.
3. **Semantics matter as much as wire compatibility.** A change that still parses but changes the meaning of an existing field is a breaking protocol change.
4. **Measurements must remain interpretable over time.** GIO may retain measurements longer than the lifetime of the software that produced them, so historical data must not depend on transient implementation details.
5. **Protocol surface area stays small.** A type belongs here only when independent GIO components need to agree on it.
   Protocol semantics should avoid forcing every producer to preserve low-level
   transport or application wire details unless the observable has material
   measurement value.

The enforceable compatibility policy is documented in [COMPATIBILITY.md](COMPATIBILITY.md).

## Repository layout

```text
.
├── proto/                  # Canonical .proto sources
├── harness/                # Internal conformance tests and fixtures
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

Install [Buf](https://buf.build/docs/installation/) (CI uses 1.72.0), Python 3.8 or newer, and GNU Make or a compatible `make` implementation. Python is used only by the repository-internal conformance harness and requires no third-party packages.

No `protoc`, Rust, Node.js, SDK toolchain, Docker runtime, or Buf Schema Registry account is required. The harness uses Buf's dynamic message conversion and does not generate or commit bindings.

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
make test          # Run wire and semantic conformance fixtures
make check         # Run the complete validation suite
```

`make check` is the authoritative local equivalent of CI. Measurement v1
establishes the first compatibility baseline; after it reaches `main`, breaking
checks protect every subsequent schema change. A checkout whose target branch
still has no `.proto` files reports that the baseline check was skipped.
An unresolvable baseline fails instead of skipping. Use
`make breaking BREAKING_BASE=<commit-or-ref>` to compare an exact target; fetch
the target branch first when checking against a newer revision of `main`.

The harness validates readable protobuf-JSON fixtures by encoding and decoding
them through the real schema, then applies the small set of semantic invariants
that Buf cannot express, including timestamp ordering and status/error/result
relationships. See [harness/README.md](harness/README.md) for its deliberately
limited scope. Harness code is repository-internal and is not a supported API.
Binary tests cover unknown fields, unknown enum numbers, optional presence, and
`oneof` decoding. Unknown future semantics are distinguished from malformed wire
data and from violations of known GIO rules.

### 5. Open a focused pull request

A protocol PR should explain the **semantic contract**, not only the syntax change. Reviewers should be able to determine:

- what new information is being represented;
- which components are expected to produce and consume it;
- whether old producers can communicate with new consumers and vice versa;
- whether persisted historical measurements retain their original meaning;
- why the change belongs in the shared protocol rather than one implementation.

CI verifies formatting, linting, schema compilation, breaking compatibility
against the exact PR base commit, and conformance tests. Documentation-only
changes skip protocol jobs while the stable `CI gate` still reports a result.

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

`gio-protocol` contains the initial Measurement v1 contract. The repository deliberately does not publish SDKs or generated language packages yet. Those may be added later if repeated consumer-side code generation becomes sufficiently costly to justify a separate SDK distribution layer, but no such packages exist today.

Until then, keep this repository focused on one thing: a precise, durable, language-independent contract for the Global Internet Observatory.
