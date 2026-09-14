# Task Assignment / Lease v1

Task Lease v1 is a pull-based control-plane protocol. An authenticated probe
uses its Registration v1 control bearer credential to poll for work, executes
one bounded measurement, sends that Measurement through authenticated Ingestion
v1, and then finalizes the lease. This package defines messages and observable
HTTP semantics only; it defines no RPC service, scheduler, database, or runtime.

The control plane permits at most one active, unexpired lease per probe and at
most one active lease per task. An acquire request has no client identity or
idempotency key: the authenticated principal is the probe. If a response is
lost after a durable lease commit, a repeated acquire returns the exact active
lease (task ID, lease ID, attempt, task specification, and expiry). If no task
is eligible and the probe has no active lease, the server returns `200` with
`NoTaskAvailable`.

Each `TaskLease` is exactly one execution attempt and contains one immutable
`task_id`, one unique `lease_id`, a one-based `attempt`, server-authoritative
`expires_at`, and exactly one `MeasurementTask`. Lease renewal, extension,
cancellation, and decline are not defined in v1. When an uncompleted lease
expires, the task may be assigned again with the same `task_id`, a new
`lease_id`, and `attempt + 1`. Execution is therefore at-least-once, never
exactly-once.

`MeasurementTask` supports only the four existing measurement families:

- `DnsTask`: non-empty query name without a trailing dot, QTYPE 1–65535, and
  optional existing `gio.measurement.v1.DnsTransport` and
  `gio.common.v1.NetworkEndpoint` resolver.
- `HttpTask`: one absolute HTTP or HTTPS URL and an implicit GET. It has no
  request body, cookies, proxy, redirect policy, or credential injection.
- `TcpTask`: one existing `gio.common.v1.NetworkEndpoint` remote endpoint,
  with port 1–65535.
- `TlsTask`: one existing `gio.common.v1.NetworkEndpoint` remote endpoint and
  optional non-empty SNI `server_name`.

No duplicate endpoint, target, IP, or transport primitives are introduced.
Task timeout configuration is intentionally absent and remains a bounded probe
default; lease expiry is not an execution-timeout field. Unknown protobuf fields
alone do not invalidate known semantics, but an unknown task kind cannot be
executed by a v1 probe. If a lease is reacquired with a changed task
specification, task ID, attempt, or expiry, the probe MUST treat it as a
server/protocol integrity error and MUST NOT silently execute the changed data.

When a probe first accepts a lease, it MUST durably bind that `lease_id` to one
locally generated `measurement_id` before execution. Reacquiring the same lease
reuses that ID. A new lease ID for a later attempt gets a new measurement ID.
Execution failures still produce a FAILED Measurement with errors. Completion
is permitted only after authenticated Ingestion v1 returns `STORED` or
`ALREADY_STORED`; `RETRY`, `REJECTED`, and transport failure never permit
completion. This preserves the ordering:

```text
lease -> execute -> persist Measurement -> authenticated ingestion ACK
      -> complete lease
```

The task payload contains no authorization headers, bearer credentials,
cookies, proxy passwords, or private keys. Scheduling policy (FIFO, priority,
fairness, region, ASN, and capacity) and capability advertisement are outside
the protocol. Remote attestation, hardware identity, malware resistance, and
exactly-once execution are also outside v1.

The threat model includes stolen control credentials, lease replay, lost acquire
or completion responses, probe crashes after execution or ingestion, expiry
during ingestion retry, duplicate execution after expiry, foreign-lease
probing, changed completion replay, redirect credential leakage, malicious task
payloads, and a server returning changed data under one lease. Registration v1
and Task Lease v1 do not solve remote attestation, hardware identity, malware
on a probe, or distributed scheduler consensus.
