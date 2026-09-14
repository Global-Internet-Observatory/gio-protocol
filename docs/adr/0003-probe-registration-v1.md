# ADR 0003: Probe Registration & Credential Provisioning v1

## Status

Accepted for the `gio.control.v1` protocol contract.

## Decision

Define only `RegisterProbeRequest` and `RegisterProbeResponse` in
`proto/gio/control/v1/registration.proto`. Bind a probe installation's opaque,
stable `registration_id` and two distinct probe-generated bearer credentials to
a control-plane-assigned `probe_id` through the HTTP profile in `HTTP.md`.

The probe generates 32 random CSPRNG bytes for each runtime credential,
encodes them as unpadded base64url, and durably persists the registration ID and
both credentials before the first network attempt. Runtime credentials are
therefore available for an exact retry even if the server commits and the
response is lost. The server need only retain protected verifiers, rather than
recoverable plaintext runtime tokens. The wire contract intentionally does not
mandate SHA-256, HMAC, a KDF, a database schema, or a secret manager.

`registration_id` is separate from `probe_id`: the former is a client-generated
idempotency identity for an installation, while the latter is the server-owned
canonical GIO principal used by Measurement and Ingestion Authentication v1.
The enrollment credential authorizes one registration only and is distinct from
both runtime credentials. Control and ingestion credentials have separate
purposes and bindings.

## Idempotency and atomicity

An exact retry returns `200` and the original `probe_id`. Changed credentials
for an existing registration return `409` without overwrite or rotation. A
different valid enrollment identity using an occupied registration ID also gets
`409`; an enrollment credential reused for another registration gets `401` to
avoid a lifecycle oracle. Enrollment authentication precedes request parsing or
state disclosure, so invalid enrollment plus malformed or colliding input is
always `401`.

Success is observable only after durable ownership of probe identity,
registration binding, both protected credential verifiers, and enrollment
consumption/binding. These are one logical atomic operation: all state commits
or none does. Registration is semantic/idempotent state and does not require
preserving exact request bytes; unknown protobuf fields alone are acceptable.

## Consequences and deferred work

The request body contains two raw secrets, so HTTPS, no automatic redirects,
strict secret redaction, and no full-body diagnostics are mandatory. This
protocol does not provide hardware identity, attestation, Sybil resistance,
credential rotation/revocation operations, enrollment issuance, admin APIs,
capability metadata, task assignment, leases, heartbeat, scheduling, or runtime
changes. **Task Lease v1 is the next control-plane protocol.**
