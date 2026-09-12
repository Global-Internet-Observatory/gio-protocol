# ADR 0001: Ingestion v1 exact-byte idempotency and acknowledgement

Status: Proposed with Ingestion v1.

## Context

A probe's durable spool holds serialized Measurement v1 records. The probe may
remove its copy after the ingestion system acknowledges durable ownership.
Independent releases can encounter Measurement fields they do not understand,
and lost responses make duplicate submissions normal.

## Decision

Ingestion uses `bytes measurement_bytes`, not a nested
`gio.measurement.v1.Measurement` field. The bytes are transferred unchanged from
the spool through ingestion. Receivers decode a view for semantic validation but
retain the original payload. This preserves unknown fields and exact wire
encoding; decode/re-encode can discard fields or change serialization even when
known values remain equivalent.

Each upload and ACK carries both `measurement_id` and a 32-byte SHA-256 digest of
the exact payload. The ID is the logical idempotency key. The digest binds the
ACK to the pending bytes, so an ACK for another payload with the same ID cannot
release the wrong local record. ID alone is insufficient; digest alone cannot
establish the logical execution identity. The digest is not authentication.

Only a valid, fully correlated response containing `STORED` or `ALREADY_STORED`
for the exact ID/digest permits deletion, and only when it arrives over an
authenticated, integrity-protected HTTPS connection whose server identity the
client verified. Both statuses assert durable ownership, not volatile queueing.
An exact retry is `ALREADY_STORED`; conflicting bytes under an existing ID are
`REJECTED` without overwrite. `RETRY` remains pending and `REJECTED` remains
preserved for operator-visible handling.

## Consequences

Delivery is at-least-once. A crash after durable server acceptance but before
local removal may redeliver the same bytes. Server deduplication and durable
identity binding are required; exactly-once delivery and global ordering are not
promised. ACK order is only request/response correlation.

The envelope cannot provide generated-language accessors for nested Measurement
fields without an explicit decode step. This is intentional. Implementations
must budget for payload validation and hashing, preserve raw bytes, and validate
the complete ACK set before deletion. ID plus SHA-256 prevents stale or
mismatched acknowledgements from releasing the wrong payload, but does not
authenticate the collector. Production deletion therefore additionally requires
authenticated, integrity-protected server TLS. Plain HTTP is limited to
loopback and deterministic local testing, where its acknowledgements cannot
authorize production deletion.

Ingestion v1 intentionally uses authenticated TLS for server-origin integrity
in the initial HTTP profile rather than adding application-layer signatures.
Signatures would introduce key distribution, rotation, and canonicalization
concerns; client authentication and authorization remain a separate future
design problem. TLS server authentication is not a substitute for those future
client-side controls.

This decision defines no collector, storage schema, production probe sink, SDK,
or control plane. The normative contract is
[Ingestion v1](../../proto/gio/ingestion/v1/README.md) and its
[HTTP profile](../../proto/gio/ingestion/v1/HTTP.md).
