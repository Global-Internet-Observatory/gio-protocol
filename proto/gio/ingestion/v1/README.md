# Ingestion v1 contract

`gio.ingestion.v1` transfers existing Measurement v1 records and acknowledges
durable ownership. It does not describe measurement execution, scheduling,
registration, authentication, or a collector implementation. The `.proto`
comments and this document are normative; **MUST**, **MUST NOT**, **SHOULD**, and
**MAY** express protocol requirements.

```text
probe durable pending record
  -> exact serialized Measurement v1 bytes
  -> SubmitMeasurementsRequest
  -> collector validation and durable ownership
  -> SubmitMeasurementsResponse
  -> matching per-record ACK permits local removal
```

Measurement v1 is the observation/result contract. Ingestion v1 is the transfer
and durability acknowledgement contract. This package does not alter any
[Measurement v1 semantics](../../measurement/v1/README.md).

## Identity and exact bytes

| Identity | Meaning |
| --- | --- |
| `measurement_id` | Non-empty logical idempotency key, equal to decoded `Measurement.measurement_id` |
| `payload_sha256` | Exactly 32 bytes: SHA-256 of `measurement_bytes` exactly |
| `measurement_bytes` | Original serialized `gio.measurement.v1.Measurement` bytes |

Senders and forwarding components MUST preserve `measurement_bytes` byte for
byte, including unknown protobuf fields. They MUST NOT decode and re-encode the
Measurement to construct the upload, even if the decoded meaning is unchanged.
Protobuf serialization is not canonical: two encodings of the same decoded
message can have different digests. No normalization, JSON conversion, sorting,
or deterministic-serialization requirement is introduced here.

The receiver MUST decode the payload using Measurement v1 and validate its
known envelope and result semantics before accepting it. It MUST reject malformed
protobuf, invalid Measurement semantics, empty or mismatched IDs, a digest whose
length is not 32 bytes, and a digest that does not match the exact payload.
Unknown fields alone are not invalid. Unknown semantic values that the receiver
cannot validate MUST NOT be certified as accepted; they may be rejected as
unsupported input. Validation does not authorize rewriting the stored payload.

The digest binds identity to bytes; it is not a signature or authentication
mechanism. Authentication and authorization are deferred.

## Batch submission and correlation

`SubmitMeasurementsRequest.measurements` MUST contain at least one record.
Measurement IDs MUST be unique within the request. There is no protocol-fixed
maximum batch count; transports and servers MAY impose byte/count limits.
Clients MUST tolerate size rejection and retain the affected records.

A valid application response MUST contain exactly one acknowledgement per
submitted record, in the same order as the request. It MUST NOT contain missing,
extra, or duplicate ACKs. Each ACK ID MUST equal the corresponding submitted ID,
and its digest MUST equal that record's submitted `payload_sha256`. Every ACK
digest MUST have length 32; `UNSPECIFIED` is invalid. Unknown future status values
do not authorize deletion and require newer semantics.

Clients MUST validate the entire ACK set before applying any local deletion.
An invalid set makes the response untrusted; all affected records remain
preserved. This correlation ordering is local to one request/response pair. It
does not imply global ingestion, execution, or delivery ordering.

Empty/duplicate wrapper IDs or malformed digest lengths prevent unambiguous,
valid ACK correlation. A receiver MUST reject such a request at the request
level, without acceptance ACKs. For a correlatable record with invalid payload
bytes, ID mismatch, digest mismatch, or unsupported semantics, it MUST NOT return
`STORED`/`ALREADY_STORED`; it MAY return `REJECTED` echoing the submitted wrapper ID
and 32-byte digest. The HTTP profile defines request-level failure handling.

## Deletion-safe acknowledgements

A probe MAY remove a pending record only after a valid application response and
only when all three conditions hold:

```text
ack.measurement_id == pending Measurement ID
AND ack.payload_sha256 == SHA256(exact pending bytes)
AND ack.status IN {STORED, ALREADY_STORED}
```

ID alone, digest alone, a successful HTTP status, or successful transmission is
insufficient. Production of a valid Measurement and durable ingestion of that
Measurement are separate lifecycle events.

| Status | Durable ownership | Probe consequence |
| --- | --- | --- |
| `STORED` | Exact ID and bytes newly durably accepted | Matching ACK permits removal |
| `ALREADY_STORED` | Exact ID and bytes already durably owned | Same removal semantics as `STORED` |
| `RETRY` | This record was not durably accepted | Preserve and retry later |
| `REJECTED` | This record was not durably accepted | Preserve for operator-visible/dead-letter handling; do not retry identical bytes forever automatically |

`STORED` MUST follow validation and crossing the collector's durable ownership
boundary, such as durable storage or durable transaction ownership. Receiving
bytes or placing them only in a volatile queue MUST NOT produce `STORED`.
The same durable obligation applies to `ALREADY_STORED`. The collector must own
the exact payload after the probe removes its copy; storage technology and
retention policy are implementation concerns, not defined here.

`RETRY` covers temporary failures such as storage/dependency outages or capacity
pressure. Retry timing and backoff are not encoded in v1. `REJECTED` covers
non-retryable identical input, including invalid payloads and identity conflicts.
`detail` is diagnostic text only; clients MUST NOT parse it for deletion or retry
decisions. It can contain sensitive information and is not safe for public logs
by default. `REJECTED` MUST NOT cause silent deletion or data loss on the probe.

Mixed outcomes are valid: a response may acknowledge A as `STORED`, B as
`ALREADY_STORED`, C as `RETRY`, and D as `REJECTED`. After validating the complete
ACK set, the client can independently resolve A/B, retain C for retry, and
preserve D for operator action. A valid negative outcome for one record does not
invalidate successful outcomes for other records.

## Idempotency and durability

Delivery is **at-least-once**. Duplicate submissions are normal after a lost
response, timeout, or crash between delivery and local acknowledgement. Servers
MUST deduplicate by logical measurement ID and enforce its binding to exact bytes.
Concurrent submissions for one ID MUST NOT overwrite that binding or both accept
conflicting payloads.

| Existing durable ownership | Submission | Required outcome |
| --- | --- | --- |
| None | ID A, bytes with hash X | `STORED(A, X)` only after durable ownership; otherwise `RETRY`/`REJECTED` |
| A with exact bytes/hash X | A with those exact bytes/hash X | `ALREADY_STORED(A, X)` |
| A with bytes/hash X | A with different bytes/hash Y | `REJECTED(A, Y)`, diagnostic detail indicating identity conflict; existing A/X MUST NOT be overwritten |

Different bytes under the same ID are not an ordinary duplicate, including a
different serialization of the same decoded Measurement. `ALREADY_STORED` asserts
ownership of exact bytes, not merely a matching ID or a known digest collision.
Deduplication knowledge MUST remain sufficient to enforce this binding for
retries; v1 defines no expiry window after which conflicting reuse is allowed.

A transport failure after durable acceptance can leave the client uncertain.
It keeps the record and retries; a later exact retry receives `ALREADY_STORED`.
Exactly-once delivery and global ordering are not promised.

## Transport and scope

The initial normative [HTTP transport profile](HTTP.md) uses protobuf request and
response bodies. No RPC service or SDK is defined. Authentication, production
storage, scheduling, registration, heartbeats, fleet control, and remote
configuration remain out of scope. Consumers pin a repository revision and
generate bindings according to repository policy.
