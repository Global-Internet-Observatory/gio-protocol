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
returns the same lease, task specification, attempt, expiry, and assigned
`measurement_id`. `NoTaskAvailable` is an explicit `200` outcome rather than
`204`.

Each lease is exactly one bounded Measurement execution. A task has an
immutable server-assigned `task_id`; each lease attempt has a unique
server-assigned `lease_id` and one-based attempt number. After expiry, the task
may be leased again with a new lease ID and incremented attempt. Execution is
at-least-once. Renewal, cancellation, decline, scheduler policy, and
capability advertisement are deferred.

The four task kinds reuse `gio.common.v1.NetworkEndpoint` and
`gio.measurement.v1.DnsTransport`; no duplicate endpoint or target primitive is
introduced. DNS dispatch is intentionally limited to A/AAAA over UDP (an
absent transport means UDP), even though `DnsResult` can describe additional
transport observations. HTTP tasks are GET-only, credential-free, require a
valid HTTP(S) authority and port, use no implicit proxy, and do not follow
redirects. Per-task timeout is absent because lease expiry and probe execution
bounds are different concepts.

The control plane assigns one opaque `measurement_id` per lease attempt as part
of the durable lease transaction. The probe persists the complete lease and
uses that exact ID in the Measurement. It must persist and ingest the
Measurement first, accepting only `STORED` or `ALREADY_STORED`, before calling
`POST /v1/task-leases:complete`. Those ACKs authorize an attempt but are not
proof for the control plane: before a new finalization, the control plane
independently verifies trusted durable ingestion ownership, the authenticated
probe principal, Measurement v1 semantics, and task mapping. FAILED
Measurements are valid executions and are completed after successful trusted
verification. `REJECTED` or transient ingestion outcomes do not complete the
lease. No public collector lookup endpoint or signed receipt is frozen.

Client-generated IDs were rejected for leased work: a client-supplied ID is an
assertion that a control-token holder can invent and cannot prove durable
ingestion ownership. Server assignment makes the expected execution identity
immutable and lets completion bind to trusted collector state.

Server assignment has two independent purposes: it binds one expected
Measurement to one lease attempt, and it supplies a globally collision-resistant
ID that another probe cannot feasibly predict and preempt through the global
Ingestion namespace. Production Task Lease IDs MUST come from a CSPRNG with at
least 128 bits of unpredictability (256 bits recommended). Predictable
sequences, counters, database IDs, and timestamp-only values are forbidden;
UUID/ULID or any other textual syntax is not required. The ID is opaque and not
an authentication credential. Ingestion v1's exact-ID/bytes rules and global
namespace remain unchanged.

Task execution has a normative mapping to Measurement intent: DNS copies the
exact query name and QTYPE into the DNS kind/target, HTTP copies the exact URL
and uses GET, TCP copies the endpoint into the TCP_CONNECT target/result, and
TLS copies the endpoint plus optional exact server name into the
TLS_HANDSHAKE target/result. A FAILED Measurement retains the matching kind and
target but has no typed result. The Measurement wire does not gain lease fields.

Completion is an immutable durable transition. An exact retry returns the same
correlated `200` response; a changed measurement ID, stale lease, task mismatch,
or attempt mismatch returns `409`. Unknown and foreign leases both return
`404` to avoid a lease-existence oracle. Authentication always precedes
request parsing and lease lookup, so invalid control credentials return `401`
without scheduling or lease-state disclosure.

## Consequences and deferred work

Task Lease v1 defines no secret-bearing fields and forbids URL userinfo; task
authors must not place secrets in URL path, query, or fragment. The
contract does not provide exactly-once execution, attestation, hardware
identity, malware resistance, distributed scheduler consensus, renewal,
cancellation, heartbeat extension, admin issuance, or runtime implementation.
A stolen control credential can poll work and hold a lease until expiry, but it
cannot finalize a fresh lease without trusted durable ingestion ownership. The
control credential alone cannot substitute a Measurement ID or stored
Measurement.

The threat model also includes cross-principal Measurement-ID preemption: a
probe with its own valid ingestion credential must not be able to guess a
future leased ID and cause a conflicting upload. This requirement protects
unassigned IDs; it does not make an already assigned ID secret.
