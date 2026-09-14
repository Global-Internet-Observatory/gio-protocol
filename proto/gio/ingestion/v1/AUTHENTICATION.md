# Ingestion Authentication v1

## Scope

Ingestion Authentication v1 is an HTTP transport profile for `gio.ingestion.v1`.
It answers who may submit a request and binds that authenticated identity to the
`probe_id` carried by each Measurement. It does not add authentication fields to
Measurement v1 or to the Ingestion v1 protobuf messages. The Measurement and
Ingestion v1 wire formats are unchanged.

A production endpoint implementing this profile MUST require authenticated TLS
(HTTPS) and an `Authorization` header. A loopback or development endpoint MAY be
explicitly unauthenticated, but it is not Authentication v1 production
conformance and plaintext bearer traffic MUST NOT be used in production.

## HTTP profile

```http
POST https://<configured-ingestion-origin>/v1/measurements:ingest
Authorization: Bearer <opaque-token>
Content-Type: application/x-protobuf
Accept: application/x-protobuf

<serialized gio.ingestion.v1.SubmitMeasurementsRequest>
```

The scheme comparison is case-insensitive (`Bearer`, `bearer`, and so on). The
credential value is opaque, non-empty, and must not contain whitespace. A server
MUST reject requests with missing or malformed authorization, multiple
`Authorization` headers, multiple bearer credentials, comma-combined credentials,
or an empty credential. Query-string and cookie credentials are not accepted.
The token MUST NOT be echoed in a response.

A `401 Unauthorized` response MAY include `WWW-Authenticate: Bearer`; it MUST
not include secret-sensitive token diagnostics. A `403 Forbidden` response does
not require `WWW-Authenticate`. Authentication error bodies are optional and
implementation-defined (and SHOULD be bounded); clients MUST NOT parse any non-2xx body as a
`SubmitMeasurementsResponse` or ACK.

## Principal model and binding

A credential verifier maps an opaque credential to one authenticated probe
principal:

```text
opaque credential -> credential verifier -> probe principal -> probe_id string
```

The protocol-visible identity of the principal is exactly one `probe_id`. It MUST
be non-empty under the existing Measurement v1 rule and MUST equal
`measurement.probe.probe_id` exactly. No trimming, case folding, Unicode
normalization, aliases, prefixes, or `deployment_id` fallback are allowed. This
profile authenticates no other field, including deployment, location, network,
target, or measurement kind.

There is one principal per HTTP request. Every decodable Measurement that carries
a non-empty `probe_id` MUST either match the authenticated principal exactly or
cause the whole request to fail with `403 Forbidden`. A decodable Measurement
with a missing or empty `probe_id` does not make an authorization claim for
another principal; it remains a Measurement semantic validation failure and
follows the existing per-record `REJECTED` semantics. An explicit mismatch MUST
not produce partial ACKs or mutate storage for the batch.

Authentication and authorization are transport-context decisions. The token is
never part of Measurement protobuf bytes, an ingestion wrapper, an ACK, or a
rejection detail.

## Failure classes and ordering

Implementations may use different internal call order, but their observable
semantics MUST provide this boundary before idempotency disclosure or durable
ownership:

```text
HTTPS transport established
  -> parse Authorization
  -> authenticate credential to one principal
  -> decode and validate request wrapper
  -> decode Measurement and compare probe_id
  -> apply existing Measurement semantic, digest, and ID validation
  -> durable store and ACK
```

- Missing, malformed, unknown, expired, or revoked credentials are
  `401 Unauthorized`.
- A valid credential whose request contains a different `probe_id` is
  `403 Forbidden`.
- After authentication, the request wrapper is validated. A Measurement that
  cannot be decoded has no identity claim and remains an existing per-record
  validation failure, represented by `INGESTION_STATUS_REJECTED` when its
  wrapper is correlatable. A decodable Measurement with a missing or empty
  `probe_id` is likewise semantic-invalid and is `REJECTED`. A decodable
  Measurement with a non-empty `probe_id` different from the principal is an
  authorization failure and makes the whole request `403`.
- `429`, `5xx`, network, TLS, and timeout behavior remains the existing retryable
  transport/service behavior. Other 4xx behavior remains the existing
  request-level rejection profile.

Authorization is a complete batch preflight. If one record is malformed or
semantic-invalid and another record makes an explicit unauthorized identity
claim, the explicit claim wins: the whole request is `403`, with zero ACKs and
zero durable mutation. A batch containing only malformed or missing-identity
records can continue to the existing per-record `REJECTED` semantics.

A `401` or `403` request MUST NOT become `STORED`, `ALREADY_STORED`, `RETRY`, or
`REJECTED` ACK data. It MUST NOT authorize local deletion. Unauthorized data MUST
never become durable storage or receive an ACK that could authorize deletion.

Authorization is checked before idempotency disclosure. If ID `M` and exact
bytes are already stored for probe A, a probe B credential cannot learn that by
submitting bytes whose payload claims probe A: the result is still `403`, never
`ALREADY_STORED`. Responses for `401` and `403` MUST NOT disclose existence,
digests, bytes, conflicts, or another probe's identity.

## Batch and existing ID semantics

A mixed-identity batch is one request-level authorization failure. There is no
partial acceptance. Once all records pass identity authorization, existing
Ingestion v1 rules apply independently per record: exact ID and bytes may produce
`ALREADY_STORED`; a same-ID, different-byte submission remains `REJECTED`.
Authentication does not replace the exact-byte SHA-256 check or change global
measurement-ID semantics. For example, a valid probe B credential submitting
ID `M` with payload `probe_id=probe-B` still reaches the existing global ID rule:
if probe A already owns different bytes under `M`, the outcome is
`REJECTED`, not a new probe namespace.

| Credential | Payload `probe_id` | Observable result |
| --- | --- | --- |
| missing, invalid, revoked, or expired | any | HTTP `401`; no ACK |
| probe A | probe B | HTTP `403`; no partial ACK |
| probe A | probe A, invalid Measurement | `REJECTED` ACK under normal ingestion rules |
| probe A | probe A, new valid record | `STORED` ACK after durable ownership |
| probe A | probe A, exact retry | `ALREADY_STORED` ACK |
| probe A | probe A, temporary service failure | existing retryable `RETRY`/transport behavior |

## Deletion authorization

A probe may remove a durable pending record only when the configured trusted
server implements this profile and all existing ACK conditions hold:

```text
trusted authenticated HTTPS
AND successful 2xx response
AND decodable complete correlated ACK set
AND matching measurement_id
AND matching SHA-256 of exact bytes
AND status is STORED or ALREADY_STORED
```

The ACK is not a cryptographic proof of client authentication; this is a
security precondition supplied by the configured server. `401`, `403`, and every
non-2xx outcome never authorize deletion and are never converted to protocol
`REJECTED` ACKs. A probe MAY retain durable bytes and surface an operator-visible
credential failure; retry policy is implementation-defined but should avoid a
tight busy loop.

## Credential lifecycle and provisioning

Credentials are opaque bearer secrets provisioned or durably bound by a
trusted credential authority to one probe principal. Authentication v1 defines
credential verification and principal binding; it does not prescribe whether
the random credential value is generated by the server, an operator, or a
registration client. Probe Registration v1 may use a probe-generated bearer
value that the control plane durably binds to the assigned `probe_id`.

Credentials MUST be generated with a cryptographically secure random source and
provide at least 128 bits of entropy; 256 random bits or more are recommended.
Base64url without padding is a possible encoding, but no token alphabet or
format is part of Authentication v1. Consumers MUST treat the value as an
opaque string and MUST NOT decode it to obtain a `probe_id`, interpret token
fields, require JWT claims, or derive identity from token structure.

A credential can be active, revoked, expired, or unknown. Active credentials
authenticate; revoked, expired, and unknown credentials all produce the same
`401` behavior so the endpoint does not become a credential oracle. A probe may
have multiple simultaneously active credentials, which permits issue/deploy,
then revoke of an old credential without an outage. Automatic rotation is not
specified.

Authentication v1 does not define how credentials are issued or recovered.
Operator provisioning is sufficient. Registration, bootstrap/enrollment, OAuth,
OIDC, fleet identity, remote attestation, admin APIs, and credential databases
are out of scope.

Servers SHOULD avoid storing bearer credentials in plaintext when a protected
verifier representation is sufficient. A keyed verifier or other appropriately
protected representation is preferable to an unprotected bare hash; the exact
storage algorithm and schema are implementation details. Secret comparisons
SHOULD use a suitable constant-time implementation where direct comparison is
performed.

## Client and server handling

Clients MUST NOT put credentials in URLs, cookies, Measurement protobufs, ACKs,
rejection details, or logs. They SHOULD use deployment-appropriate OS or
filesystem secret protections. Servers MUST NOT log the raw `Authorization`
header or bearer token, and should avoid logging token verifiers suitable for
offline guessing. Servers MAY log the authenticated `probe_id`, HTTP status,
and bounded outcome counts. A non-secret implementation credential identifier
may be logged if one exists, but the protocol does not define one.

## Security considerations and limitations

Authenticated TLS protects bearer credentials in transit only when certificate
and service identity verification is enabled. Plaintext HTTP can expose a token
and is limited to local, non-production harness use. A stolen bearer token lets
an attacker act as that probe until revocation or expiry. Bearer replay is
allowed: at-least-once delivery and idempotency require an authenticated probe
to retry the same ID and bytes and receive `ALREADY_STORED`.

Authentication v1 does not provide proof-of-possession, request signatures,
anti-replay nonces, hardware binding, or remote attestation. Future mechanisms
such as mTLS, signed requests, OAuth/OIDC gateways, short-lived credentials, or
hardware identity must still map to the same authenticated probe principal
contract.

## Conformance requirements

The repository harness uses a fake map (`token-A` to probe A, `token-B` to probe
B, plus revoked and expired entries) only to exercise these normative outcomes;
those fixtures do not define a production token format. It covers:

- missing, empty, malformed, unknown, revoked, expired, duplicate, and
  comma-combined credentials -> `401`;
- valid probe A credential with probe A -> normal ingestion and `STORED`;
- valid probe A credential with probe B -> `403`;
- a mixed probe A/probe B batch -> request-level `403` with no mutation;
- malformed plus unauthorized, and semantic-invalid plus unauthorized, mixed
  batches -> request-level `403` with zero ACKs and no mutation;
- an existing record attempted with the wrong principal -> `403`, never
  `ALREADY_STORED` and never a storage disclosure;
- valid identity plus invalid Measurement -> normal `REJECTED` behavior;
- exact authenticated retry -> `ALREADY_STORED`;
- authorization failures produce no ACK/deletion authorization;
- existing Measurement/Ingestion wire, unknown-field, digest, ACK correlation,
  idempotency, and durable-ownership regressions remain covered.

## Compatibility and versioning

This is an HTTP/profile-level Authentication v1 extension. It does not create
`gio.ingestion.v2`, add a protobuf package, or bump a schema version. Existing
Ingestion v1 protobuf producers and consumers remain wire-compatible, while a
production authenticated endpoint is a stricter HTTP profile. Unauthenticated
local development remains possible only when explicitly selected and is not
production-conformant.

## Out of scope

Credential issuance service, probe registration, control plane, collector
middleware, probe token-loading implementation, credential DB schema, OAuth or
JWT, mTLS CA, refresh tokens, SDKs, generated clients, and deployment manifests
are deliberately deferred.
