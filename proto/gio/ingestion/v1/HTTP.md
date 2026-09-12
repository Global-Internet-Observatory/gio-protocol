# Ingestion v1 HTTP transport profile

This is the normative initial transport for `gio.ingestion.v1`. It does not
define a running service, server discovery, authentication, or authorization.

## Request

```http
POST /v1/measurements:ingest
Content-Type: application/x-protobuf
Accept: application/x-protobuf

<serialized gio.ingestion.v1.SubmitMeasurementsRequest>
```

The body MUST be protobuf wire bytes. JSON is not a normative ingestion format.
The record payloads MUST be the exact pending Measurement bytes. V1 adds no
protobuf compression fields or compression negotiation semantics.

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
before acting on any ACK. Only matching `STORED`/`ALREADY_STORED` ACKs authorize
removal. HTTP 2xx alone never does.

## Failure handling

| Condition | Required client behavior |
| --- | --- |
| Timeout or connection failure | No reliable ACK exists; retain all affected records. The collector may already own them, so retry with stable IDs and exact bytes. |
| HTTP 429 or 5xx | Treat as retryable transport failure; retain records and do not acknowledge locally. |
| HTTP 413 | Retain records; retry with smaller batches where possible. A single oversized record still requires preservation and operator-visible handling. |
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

Authentication, TLS identity policy, credentials, and endpoint provisioning will
be specified separately. This profile adds no token, key, registration, or
control-plane fields to the protobuf contract.
