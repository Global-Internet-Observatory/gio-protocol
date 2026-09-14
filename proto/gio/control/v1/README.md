# Probe Registration & Credential Provisioning v1

`gio.control.v1` establishes a newly installed probe's durable identity and
binds its two runtime credentials. This package defines messages only; it does
not define an RPC service, gRPC, or a control-plane implementation.

Before its first network attempt, a probe generates and durably persists a
non-secret `registration_id`, a control bearer token, and an ingestion bearer
token. For both runtime token fields, Registration v1 normatively requires 32
bytes generated from a CSPRNG, encoded as RFC 4648 URL-safe base64 without
padding: exactly 43 ASCII characters from `[A-Za-z0-9_-]`. This is the
Registration v1 credential generation/input profile, not a long-term bearer
semantic format. The enrollment credential, control bearer credential, and
ingestion bearer credential MUST be pairwise distinct; `registration_id` is not
a credential.

After registration, collectors, control-plane authenticated endpoints, and
probe transports MUST treat bearer values as opaque strings. They MUST NOT
decode a token to obtain `probe_id`, interpret token fields, require JWT claims,
or derive identity from token structure. Identity comes from a protected
credential verifier bound to `probe_id`; the Registration profile does not freeze
SHA-256 or any other verifier algorithm. The reference harness uses SHA-256
only as a test model.

The probe submits `RegisterProbeRequest` using a one-time enrollment credential.
The control plane authenticates that credential, validates the request, assigns
`probe_id`, durably binds registration ID and protected credential verifiers as
one logical transaction, and then returns `RegisterProbeResponse`. The response
echoes `registration_id` and never contains either runtime token. A successful
response is valid only after strict protobuf/content-type/correlation checks.

`registration_id` is an opaque exact string: non-empty, at most 128 UTF-8
bytes, stable across retries, and not trimmed, case-folded, normalized, or
aliased. `probe_id` is always chosen by the control plane and is the canonical
identity used by Measurement and Ingestion Authentication v1.

The observable processing order is: authenticate enrollment, parse/decode the
request, validate all known Registration semantics (including pairwise
credential separation), then apply immutable conflict/idempotency rules. Thus a
valid enrollment with an occupied registration ID but malformed credentials is
`400`, while a semantically valid immutable conflict is `409`.

Registration is immutable in v1. An exact retry (same enrollment credential,
registration ID, and both token values) returns `200` with the same `probe_id`,
including after a lost response or process restart. Changed credentials for an
existing registration return `409` and never overwrite or rotate state. A
different valid enrollment identity colliding with an existing registration ID
also returns `409` without revealing the existing probe ID. Reusing an
enrollment credential for another registration returns `401`.

Enrollment credentials are one-purpose and are distinct from control and
ingestion credentials. Their issuance, expiry/revocation store, rotation, and
administrative workflows are outside this protocol. Task Assignment, Task
Lease, Heartbeat, scheduling, capability metadata, and runtime implementations
are deferred; **Task Lease v1 is the next control-plane protocol**.

Unknown protobuf fields do not invalidate otherwise valid known registration
semantics. Registration is semantic/idempotent state, rather than exact-payload
storage like Measurement Ingestion. `registration_id` is untrusted text; any
implementation that logs it MUST use structured logging or escaping and MUST
NOT interpolate raw control characters into an unstructured log line.

Only a valid correlated HTTP `200` response completes registration. All other
HTTP statuses are non-completing; invalid `200`, other `2xx`, `429`, and `5xx` use exact retry,
while all `3xx` and other `4xx` statuses require intervention.
