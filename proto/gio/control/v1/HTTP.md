# Registration v1 HTTP profile

The registration request is secret-bearing. Production deployments MUST use
authenticated HTTPS and MUST NOT automatically follow redirects.

```http
POST https://<configured-control-origin>/v1/probes:register
Authorization: Bearer <opaque-enrollment-token>
Content-Type: application/x-protobuf
Accept: application/x-protobuf

<serialized gio.control.v1.RegisterProbeRequest>
```

On success the server returns `200 OK`,
`Content-Type: application/x-protobuf`, and a serialized
`RegisterProbeResponse`. The client MUST verify the response is valid,
contains a non-empty `probe_id`, and echoes the request's exact
`registration_id` before treating registration as complete.

The server MUST authenticate the enrollment credential before parsing or
disclosing request/storage state. Missing, malformed, unknown, expired,
revoked, or consumed-for-another-registration enrollment credentials all map
to `401 Unauthorized`; v1 does not use `403`. After authentication, malformed
protobuf or invalid known request semantics map to `400 Bad Request`.
Validation precedes conflict handling: a valid enrollment plus an occupied
registration ID and malformed credentials is `400`, not `409`.

Authorization parsing reuses the Bearer boundary in [Ingestion Authentication
v1](../../ingestion/v1/AUTHENTICATION.md): scheme comparison is
case-insensitive, while the credential must be non-empty and exactly one
credential must be present. The server MUST reject missing or malformed
`Authorization`, multiple `Authorization` headers, multiple bearer
credentials, comma-combined credentials, and empty credentials. Enrollment
credentials remain opaque and do not need to use the Registration runtime-token
profile; query-string, cookie, and URL credentials are forbidden.

An authenticated immutable identity or credential conflict maps to `409 Conflict`.
`429 Too Many Requests` and `5xx` responses are temporary and safe
to retry with the exact persisted request. Network, TLS, timeout, or malformed
successful responses are also retryable with the exact request. A `401`, `400`,
or `409` requires operator/developer intervention; the probe retains its local
registration evidence and MUST NOT silently generate replacement credentials or
a new registration identity.

Clients MUST apply the following complete outcome classification:

| Outcome | Client result |
| --- | --- |
| `200` with valid `application/x-protobuf`, decodable `RegisterProbeResponse`, exact `registration_id` correlation, and non-empty `probe_id` | `complete` |
| `200` with wrong content type, malformed/undecodable response, mismatched `registration_id`, or empty `probe_id` | `retry_exact` |
| Any other `2xx` (including `201`, `202`, `204`, and `206`) | `retry_exact` |
| `429` or any `5xx` | `retry_exact` |
| Network, TLS, or local timeout failure | `retry_exact` |
| `400` or `409` | `operator_intervention` (operator/developer) |
| `401` | `operator_intervention` (operator/bootstrap) |
| Any `3xx` (`301`, `302`, `303`, `307`, `308`, or another redirect) | `operator_intervention`; MUST NOT automatically follow the redirect |
| Any other `4xx` not assigned a Registration meaning (including `403`, `404`, `405`, `408`, `410`, `418`, `422`, and `451`) | `operator_intervention` |
| Any status outside these HTTP classes | `operator_intervention` |

Only the first row can complete registration. For every non-completing outcome,
clients MUST retain the exact persisted registration intent, credentials, and
local evidence; they MUST NOT regenerate credentials or registration identity.
`retry_exact` recovers the canonical response when the server may already have
durably committed, including for invalid `200` and other `2xx` responses.
Intervention outcomes MUST be surfaced to an operator and MUST NOT trigger
automatic retries. All `3xx` responses require this same behavior and MUST NOT
be followed automatically: redirecting this secret-bearing request could send
enrollment, control, and ingestion credentials to another origin.

HTTP `408` is an actual server response and requires intervention under the
other-4xx rule; it is distinct from a local network, TLS, or connection timeout,
which uses exact retry. Unknown status values MUST NOT complete registration.

The server MUST return success only after durable ownership exists for the
probe ID, registration binding, both protected runtime credential verifiers,
and enrollment consumption/binding. It MUST perform these as one logical atomic
operation. It SHOULD discard raw runtime tokens as soon as practical and MUST
NOT log or persist ordinary diagnostics containing authorization headers,
runtime tokens, token hashes/verifiers, or full request bodies. Diagnostics may
include registration ID, assigned probe ID, and HTTP status, subject to local
privacy policy.

`registration_id` is untrusted exact UTF-8 text. Structured logging or escaping
is required when it is logged; raw control characters MUST NOT be interpolated
into an unstructured log line.

No credential may appear in a URL, query string, cookie, redirect target, ACK,
detail, or ordinary log. Enrollment proves permission to create one
registration; after success the canonical principal is `probe_id`. Control and
ingestion credentials are never interchangeable. Registration v1 does not
define credential rotation, revocation operations, enrollment issuance, or any
task/lease/heartbeat endpoint.
