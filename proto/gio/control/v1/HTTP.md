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

An authenticated immutable identity or credential conflict maps to `409 Conflict`.
`429 Too Many Requests` and `5xx` responses are temporary and safe
to retry with the exact persisted request. Network, TLS, timeout, or malformed
successful responses are also retryable with the exact request. A `401`, `400`,
or `409` requires operator/developer intervention; the probe retains its local
registration evidence and MUST NOT silently generate replacement credentials or
a new registration identity.

The server MUST return success only after durable ownership exists for the
probe ID, registration binding, both protected runtime credential verifiers,
and enrollment consumption/binding. It MUST perform these as one logical atomic
operation. It SHOULD discard raw runtime tokens as soon as practical and MUST
NOT log or persist ordinary diagnostics containing authorization headers,
runtime tokens, token hashes/verifiers, or full request bodies. Diagnostics may
include registration ID, assigned probe ID, and HTTP status, subject to local
privacy policy.

No credential may appear in a URL, query string, cookie, redirect target, ACK,
detail, or ordinary log. Enrollment proves permission to create one
registration; after success the canonical principal is `probe_id`. Control and
ingestion credentials are never interchangeable. Registration v1 does not
define credential rotation, revocation operations, enrollment issuance, or any
task/lease/heartbeat endpoint.
