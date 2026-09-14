# ADR 0004: Task Assignment / Lease v1

## Status

Accepted for the `gio.control.v1` protocol contract.

## Decision

Use short-lived pull-based HTTP leasing. A probe authenticated with its
Registration v1 control credential polls `POST /v1/tasks:lease`; the control
plane assigns at most one active lease to that probe and at most one active
lease to a task. No inbound connection, push stream, WebSocket, SSE, or RPC is
required for probes behind NAT or firewalls.

`AcquireTaskLeaseRequest` is empty because the authenticated principal is the
canonical `probe_id`. With one active lease per probe, acquire needs no client
idempotency key: after a durable commit and lost response, the next poll
returns the same lease, task specification, attempt, and expiry. `NoTaskAvailable`
is an explicit `200` outcome rather than `204`.

Each lease is exactly one bounded Measurement execution. A task has an
immutable server-assigned `task_id`; each lease attempt has a unique
server-assigned `lease_id` and one-based attempt number. After expiry, the task
may be leased again with a new lease ID and incremented attempt. Execution is
at-least-once. Renewal, cancellation, decline, scheduler policy, and
capability advertisement are deferred.

The four task kinds reuse `gio.common.v1.NetworkEndpoint` and
`gio.measurement.v1.DnsTransport`; no duplicate endpoint or target primitive is
introduced. HTTP tasks are GET-only. Per-task timeout is absent because lease
expiry and probe execution bounds are different concepts.

Before execution, the probe durably binds one locally generated
`measurement_id` to the lease ID. It must persist and ingest the Measurement
first, accepting only `STORED` or `ALREADY_STORED`, before calling
`POST /v1/task-leases:complete`. FAILED Measurements are valid executions and
are completed after successful ingestion. `REJECTED` or transient ingestion
outcomes do not complete the lease.

Completion is an immutable durable transition. An exact retry returns the same
correlated `200` response; a changed measurement ID, stale lease, task mismatch,
or attempt mismatch returns `409`. Unknown and foreign leases both return
`404` to avoid a lease-existence oracle. Authentication always precedes
request parsing and lease lookup, so invalid control credentials return `401`
without scheduling or lease-state disclosure.

## Consequences and deferred work

Task payloads contain no secrets and no task-side authorization headers. The
contract does not provide exactly-once execution, attestation, hardware
identity, malware resistance, distributed scheduler consensus, renewal,
cancellation, heartbeat extension, admin issuance, or runtime implementation.
