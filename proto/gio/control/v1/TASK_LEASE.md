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
lease (task ID, lease ID, attempt, task specification, expiry, and
server-assigned measurement ID). If no task is eligible and the probe has no
active lease, the server returns `200` with
`NoTaskAvailable`.

Each `TaskLease` is exactly one execution attempt and contains one immutable
`task_id`, one unique `lease_id`, a one-based `attempt`, server-authoritative
`expires_at`, a server-assigned opaque `measurement_id`, and exactly one
`MeasurementTask`. The measurement ID is unique per lease attempt, immutable,
and returned identically on reacquire. Lease renewal, extension,
cancellation, and decline are not defined in v1. When an uncompleted lease
expires, the task may be assigned again with the same `task_id`, a new
`lease_id`, and `attempt + 1`. Execution is therefore at-least-once, never
exactly-once.

`MeasurementTask` supports only the four existing measurement families. The
task-to-Measurement mapping below is normative; a task author cannot reinterpret
the target or result fields.

- `DnsTask`: non-empty query name without a trailing dot, QTYPE `1` (A) or
  `28` (AAAA), and UDP only. An absent transport means UDP; the explicit
  `DNS_TRANSPORT_UDP` value is also valid. TCP, TLS, and HTTPS transports are
  unsupported by Task Lease v1 even though `DnsResult` has a wider observation
  vocabulary. An absent resolver means the probe/system configured UDP
  resolver; a present resolver is the exact UDP endpoint to contact.
- `HttpTask`: one absolute, credential-free HTTP or HTTPS URL with an authority
  and an implicit GET. URL userinfo is forbidden; a specified port must parse
  and be in the inclusive range 1–65535. It has no request body, cookies,
  proxy, redirect policy, or credential injection. The probe uses no implicit
  proxy, follows no redirects, and observes a redirect response itself as the
  final response. Operators must not place secrets in URL path, query, or
  fragment.
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

The control plane assigns `measurement_id` atomically with durable lease
creation. Before execution, the probe MUST durably persist the complete lease
and use that exact ID as `Measurement.measurement_id`. Reacquiring the same
lease reuses the ID; a new lease attempt receives a new ID. Execution failures
still produce a FAILED Measurement with errors. Completion is permitted only
after authenticated Ingestion v1 returns `STORED` or `ALREADY_STORED` and the
control plane independently verifies trusted durable ingestion ownership.
`RETRY`, `REJECTED`, and transport failure never permit completion. This
preserves the ordering:

```text
lease -> execute -> persist Measurement -> authenticated ingestion ACK
      -> control-plane trusted verification -> complete lease
```

The ingestion ACK authorizes the probe to attempt completion; it is not a
server-verifiable proof. A control plane MUST verify trusted collector durable
ownership of the expected Measurement before finalizing a new lease. The
authoritative stored Measurement must have the lease-assigned ID, the same
authenticated `probe_id`, valid Measurement v1 semantics, and the matching
task mapping. A missing or mismatching Measurement prevents finalization.

## Task-to-Measurement mapping

For every leased execution, `Measurement.measurement_id` is the server-assigned
ID carried by the durable lease and persisted by the probe. Standalone,
non-leased probe executions may continue to generate their own IDs.
`Measurement.probe.probe_id` is the authenticated control principal. The task intent remains in the Measurement
even when execution fails; a FAILED Measurement has the matching `kind` and
`target` and no typed result.

- A `DnsTask` produces `kind = MEASUREMENT_KIND_DNS` and
  `target.hostname = query_name` exactly. A present `DnsResult` repeats the
  exact query name and QTYPE, uses UDP, and uses the requested resolver when one
  was supplied. When the task omitted a resolver, a usable result may report
  the actual configured resolver if it is observable.
- An `HttpTask` produces `kind = MEASUREMENT_KIND_HTTP` and
  `target.url = url` exactly. A present `HttpResult` uses method `GET` and has
  `final_url` equal to the requested URL because redirects are not followed.
- A `TcpTask` produces `kind = MEASUREMENT_KIND_TCP_CONNECT` with target IP
  address and port copied exactly from `remote_endpoint`. A present
  `TcpConnectResult.remote_endpoint` equals that endpoint.
- A `TlsTask` produces `kind = MEASUREMENT_KIND_TLS_HANDSHAKE` with target IP
  address and port copied exactly from `remote_endpoint`. If `server_name` is
  present, `target.hostname` is that exact value. A present
  `TlsHandshakeResult` repeats the endpoint and, when supplied, the exact
  server name.

The mapping does not add `task_id`, `lease_id`, or `attempt` to the Measurement
wire. Those values remain in durable control-plane lease state and the
completion binding.

Task Lease v1 defines no secret-bearing fields: it contains no authorization
headers, bearer credentials, cookies, proxy passwords, or private keys. URL
userinfo is syntactically forbidden; task authors also MUST NOT place secrets
in URL path, query, or fragment. Scheduling policy (FIFO, priority,
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
