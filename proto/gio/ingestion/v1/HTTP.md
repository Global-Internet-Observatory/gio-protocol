# Ingestion v1 HTTP transport profile

This is the normative initial transport for `gio.ingestion.v1`. Production
deletion-authorizing ingestion requires HTTPS with authenticated server TLS and
the [Ingestion Authentication v1](AUTHENTICATION.md) bearer profile. This
document defines the wire transport; it does not define a running service,
server discovery, credential issuance, or a control plane.

## Request

```http
POST https://<configured-ingestion-origin>/v1/measurements:ingest
Authorization: Bearer <opaque-token>
Content-Type: application/x-protobuf
Accept: application/x-protobuf

<serialized gio.ingestion.v1.SubmitMeasurementsRequest>
```

The body MUST be protobuf wire bytes. JSON is not a normative ingestion format.
The record payloads MUST be the exact pending Measurement bytes. V1 adds no
protobuf compression fields or compression negotiation semantics.

Production requests MUST include exactly one valid `Authorization: Bearer`
credential. Missing or invalid credentials are `401 Unauthorized`; a valid
credential whose Measurement `probe_id` does not match its authenticated
principal is a request-level `403 Forbidden`. The complete authentication,
batch, lifecycle, and security rules are in [Authentication v1](AUTHENTICATION.md).

## Valid application response

```http
2xx
Content-Type: application/x-protobuf

<serialized gio.ingestion.v1.SubmitMeasurementsResponse>
```

A 2xx response MUST include a decodable response body with the complete valid ACK
set specified by the [ingestion contract](README.md). A bodyless 204 is therefore
not a valid application response. A client MUST validate the media type, protobuf
body, ACK cardinality, uniqueness, IDs, digests, status values, and request order
before acting on any ACK. Only matching `STORED`/`ALREADY_STORED` ACKs received
over the trusted transport described below authorize removal. HTTP 2xx alone
never does.

## Transport security

Production ingestion endpoints MUST use HTTPS. Before any `STORED` or
`ALREADY_STORED` acknowledgement can authorize deletion of a local durable
record, the client MUST authenticate the server certificate or service identity
according to its configured trust policy and MUST receive the response over
that integrity-protected connection. Certificate verification and
hostname/service-identity verification MUST NOT be disabled for production
ingestion. Acknowledgements received over a transport whose server identity was
not authenticated MUST NOT authorize deletion.

Normal WebPKI/system trust, a configured private CA, or a future explicit GIO
trust mechanism may satisfy this requirement. This profile does not prescribe a
particular PKI deployment. A TLS handshake, certificate, or server-identity
validation failure means there is no trusted acknowledgement; affected records
remain pending.

Plain HTTP MAY be used for loopback, deterministic local development, and
non-production harnesses. It is not a production deletion-safe ownership proof:
an acknowledgement received over unauthenticated plaintext HTTP MUST NOT
authorize deletion. Production clients MUST NOT downgrade HTTPS to HTTP. Clients
SHOULD NOT automatically follow ingestion redirects unless explicitly
configured; any explicitly followed final destination MUST independently meet
these HTTPS and server-authentication requirements.

## Failure handling

| Condition | Required client behavior |
| --- | --- |
| Timeout or connection failure | No reliable ACK exists; retain all affected records. The collector may already own them, so retry with stable IDs and exact bytes. |
| TLS handshake, certificate, or server-identity validation failure | No trusted ACK exists; retain all affected records and do not acknowledge locally. |
| HTTP 429 or 5xx | Treat as retryable transport failure; retain records and do not acknowledge locally. |
| HTTP 413 | Retain records; retry with smaller batches where possible. A single oversized record still requires preservation and operator-visible handling. |
| HTTP 401 or 403 | Request-level authentication/authorization failure; no ACK is constructed, no storage or idempotency disclosure is allowed, and no local deletion is authorized. Preserve records and surface credential configuration failure. |
| 2xx with wrong/missing media type, missing body, or malformed protobuf | Treat as invalid/untrusted response; retain all affected records. |
| Malformed ACK set, including wrong ID/digest, missing/extra/duplicate ACK, wrong order, or `UNSPECIFIED` | Reject the entire ACK set before local deletion; retain all affected records. |
| Unknown ACK status | Do not infer acceptance; retain the affected batch until it can be interpreted safely. |
| Other 4xx | Request-level rejection; preserve records for diagnosis/correction rather than silently deleting or indefinitely retrying unchanged input. |

Non-2xx response bodies do not authorize local deletion, even if they happen to
decode as an ACK response. This profile does not freeze a complete taxonomy or
body format for HTTP errors. An implementation may expose operational limits and
diagnostics, but clients cannot infer durable acceptance from them.

Mixed `STORED`, `ALREADY_STORED`, `RETRY`, and `REJECTED` statuses belong in a valid
2xx application response; they are not replaced by one batch-wide success flag.
Retry timing/backoff and handling of optional HTTP retry hints are client policy.
Redirects are not ingestion acknowledgements and MUST NOT authorize deletion.

Authentication v1 adds no token, key, registration, or control-plane fields to
the protobuf contract; its HTTPS server-authentication requirement remains the
transport precondition for deletion-authorizing ACKs. The protobuf wire formats
for Measurement v1 and Ingestion v1 are unchanged.
