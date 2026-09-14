# Task Lease v1 HTTP profile

Production endpoints MUST use authenticated HTTPS and MUST NOT automatically
follow redirects. Bearer parsing reuses the Registration and Ingestion
Authentication v1 boundary: case-insensitive `Bearer` scheme, exactly one
non-empty credential, rejection of duplicate or comma-combined credentials,
and no query, cookie, or URL credentials.

## Acquire

```http
POST https://<configured-control-origin>/v1/tasks:lease
Authorization: Bearer <control-bearer-token>
Content-Type: application/x-protobuf
Accept: application/x-protobuf

<serialized gio.control.v1.AcquireTaskLeaseRequest>
```

The server authenticates the control credential before parsing the request,
checking active leases, or checking task availability. Invalid credentials
therefore return `401` even for malformed input, an existing active lease, or
available work. An authenticated malformed request returns `400`.

Success is `200 OK` with `Content-Type: application/x-protobuf` and a valid
`AcquireTaskLeaseResponse` containing exactly one `lease` or `no_task` outcome.
The client MUST validate the complete lease shape before executing it. Invalid
or malformed successful responses, other `2xx`, `429`, `5xx`, and network/TLS/
timeout failures are exact retries. `401`, all `3xx`, and other `4xx` require
intervention; redirects MUST NOT be followed automatically. No `204` no-task
response exists.

## Completion

```http
POST https://<configured-control-origin>/v1/task-leases:complete
Authorization: Bearer <control-bearer-token>
Content-Type: application/x-protobuf
Accept: application/x-protobuf

<serialized gio.control.v1.CompleteTaskLeaseRequest>
```

Authentication precedes parsing and all lease lookup. Invalid credentials
return `401` for malformed, unknown, foreign, expired, or finalized requests.
An authenticated malformed request returns `400`.

The probe MUST complete only after Ingestion v1 acknowledges the corresponding
Measurement as `STORED` or `ALREADY_STORED`. A valid new completion, or an exact
retry of an already finalized completion, returns `200` with
`Content-Type: application/x-protobuf` and a decodable, exactly correlated
`CompleteTaskLeaseResponse`. The server returns success only after durable
finalization of the lease and measurement ID binding. A `200` with another
media type, malformed protobuf, or any task/lease/attempt/measurement echo
mismatch is non-completing and MUST retry the exact persisted request; the
server may already have finalized the lease.

An unknown lease or a lease owned by another probe both return `404`, revealing
no lease existence distinction. An expired lease, task/attempt mismatch, or a
finalized lease with a different measurement ID returns `409`. Other `2xx`,
`429`, `5xx`, and transport failures retry the exact completion request;
`400`, `401`, `404`, `409`, all `3xx`, and other `4xx` require intervention.
No completion error envelope is defined.

## Security and lifecycle boundaries

Task Lease v1 defines no secret-bearing task fields. URL userinfo is forbidden;
task authors MUST NOT place secrets in URL path, query, or fragment. A probe
retains local execution intent through every non-success outcome and MUST NOT
silently invent a new measurement ID for the same lease. Lease expiry provides
recovery after a crash or disappearance; v1 defines no renewal, cancellation,
rejection, or heartbeat-coupled extension. The protocol is at-least-once task
execution, so duplicate attempts after expiry are expected and must be
correlated by their distinct lease and measurement IDs.
