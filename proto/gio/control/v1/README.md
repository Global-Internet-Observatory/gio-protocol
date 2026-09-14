# Probe Registration & Credential Provisioning v1

`gio.control.v1` establishes a newly installed probe's durable identity and
binds its two runtime credentials. This package defines messages only; it does
not define an RPC service, gRPC, or a control-plane implementation.

Before its first network attempt, a probe generates and durably persists a
non-secret `registration_id`, a control bearer token, and an ingestion bearer
token. The recommended GIO token profile is 32 CSPRNG bytes encoded as
unpadded base64url (43 ASCII characters). The three credentials MUST be
distinct. Consumers treat bearer values as opaque; the profile is a generation
profile, not a token meaning or verification algorithm.

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
storage like Measurement Ingestion.
