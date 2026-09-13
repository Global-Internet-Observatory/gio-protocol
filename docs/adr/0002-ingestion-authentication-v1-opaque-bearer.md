# ADR 0002: Opaque bearer authentication for Ingestion v1

Status: Proposed.

## Context

Ingestion v1 already authenticates the collector's server transport with HTTPS
and binds ACKs to exact Measurement bytes. It does not identify which probe is
uploading. A credential must therefore authorize one explicit probe identity
without adding secrets or transport metadata to Measurement v1.

## Decision

Define Authentication v1 as an HTTP profile using:

```http
Authorization: Bearer <opaque-token>
```

After verification, the server obtains exactly one authenticated probe principal
whose protocol-visible identity is `probe_id`. Every Measurement in one request
must carry that exact `measurement.probe.probe_id`; any mismatch is one request-
level `403`. Missing, malformed, unknown, expired, and revoked credentials all
return indistinguishable `401` outcomes. Authentication and authorization happen
before idempotency disclosure, storage mutation, or deletion-authorizing ACKs.

Do not alter Measurement v1 or the existing Ingestion v1 protobuf schema. Do not
freeze JWT, OAuth/OIDC, mTLS, request signing, a token alphabet, a credential
database, or an issuance flow. Credentials require at least 128 bits of CSPRNG
entropy, may have active/revoked/expired lifecycle states, and multiple active
credentials may represent one probe for rotation.

## Rationale

Opaque bearer credentials are the smallest deployable identity boundary. They
permit server-side rotation and revocation without public-key infrastructure,
keep token semantics out of clients and protobuf payloads, and leave the verifier
implementation evolvable. The resulting principal mapping gives collectors one
stable authorization semantic even if a future gateway uses mTLS, signatures, or
OAuth/OIDC.

## Consequences and limitations

A stolen token can act as its probe until revoked or expired. Replay by that same
principal is intentionally allowed because ingestion is at-least-once and
idempotent. Authentication v1 supplies no proof-of-possession, request signature,
anti-replay nonce, hardware binding, or remote attestation. Production bearer
traffic requires authenticated TLS; loopback plaintext harnesses cannot claim
production authentication.

Credential issuance, registration, recovery, probe-side secret storage,
collector middleware, and all control-plane concerns remain outside this ADR.
The normative profile is [Ingestion Authentication v1](../../proto/gio/ingestion/v1/AUTHENTICATION.md).
