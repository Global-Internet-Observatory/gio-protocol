# Measurement v1 contract

`gio.measurement.v1.Measurement` is a terminal observation record. It describes
one execution from one probe, not a scheduled job, an in-progress update, a
database row, or a command. DNS, HTTP, TCP connect, and TLS handshake are the
four supported kinds. `gio.common.v1` supplies shared identity and network types.

This document defines relationships across messages. The `.proto` comments
define field encodings, units, presence, and ordering. Repository compatibility
rules are in [COMPATIBILITY.md](../../../../COMPATIBILITY.md).

## Identity and lifecycle

An execution has a non-empty opaque `measurement_id`. Retransmission retains
the ID; executing the observation again creates a new ID. The protocol does not
require a UUID, ULID, database key, or particular delivery/deduplication mechanism.
The required `probe.probe_id` identifies the logical probe. Deployment identity
and software identity provide separate, optional provenance.

`kind`, `started_at`, `finished_at`, `probe`, `target`, and a terminal `status`
are semantically required even though protobuf can decode a message without
them. Protobuf's zero enum sentinels are not valid measurement kinds or statuses.

`kind` deliberately repeats information in the result `oneof`. A failure can
identify what was attempted without a result. A future producer can also send a
new kind and result that an older consumer can transport without interpreting.
For understood kinds, the result member must match exactly:

| Kind | Result member |
| --- | --- |
| DNS | `dns_result` |
| HTTP | `http_result` |
| TCP_CONNECT | `tcp_connect_result` |
| TLS_HANDSHAKE | `tls_handshake_result` |

| Terminal status | Matching result | Errors |
| --- | --- | --- |
| SUCCEEDED | Exactly one | None |
| FAILED | None | One or more |
| PARTIAL | Exactly one usable result | One or more |

`PARTIAL` means execution ended with a failure after producing usable observation
data. It does not mean arbitrary fields may be missing: each retained result
still follows its message contract. For example, an HTTP response can provide
its final status and headers and a captured body prefix before a connection
reset. That is PARTIAL; a timeout before any HTTP response is FAILED.

A TCP result always asserts that a connection was established. A TLS result
always asserts that the handshake completed. PARTIAL may retain these completed
observations if a separate execution failure occurred afterward; it cannot be
used to represent an unestablished TCP connection or a half-negotiated TLS session.
Do not fabricate version, cipher, endpoints, response codes, or successful
elapsed timings to satisfy the shape of a result.

Success describes observation execution, not whether the observed service is
healthy. NXDOMAIN, SERVFAIL, and an HTTP 404 or 500 can all be successfully
observed results. A DNS query used as a prerequisite for an HTTP/TCP/TLS attempt
that fails to resolve its target is instead an envelope execution error.

## Errors

Use the most specific known cause. Explicit cancellation and deadline expiry
have their own categories at every stage. Prerequisite DNS failures and known
transport failures retain their categories even when they happen during an
HTTP or TLS operation. `TLS_HANDSHAKE_FAILED` covers remaining TLS negotiation
failures; `PROTOCOL_ERROR` covers malformed or unparseable exchanges, not ordinary
negative protocol responses. `INTERNAL_ERROR` identifies a probe/local execution
failure; `OTHER` is the fallback when a failure is known but cannot be classified.

Do not encode errno numbers, vendor codes, or stack traces as new enum values.
`detail` is optional diagnostic text with no stable syntax. Consumers must not
parse it, classify errors by its wording, or assume it is safe for public display.
The errors list has no primary-error or causal-order semantics.

## Requested targets and observed context

`Target` records the requested destination. At least one non-empty hostname, IP,
or URL is required. Optional representations refer to that same requested target.
A supplied port is 1–65535; absence does not mean port zero. Do not rewrite the
target after redirects or resolution.

The actual connected TCP/TLS peer is in the result's `remote_endpoint`.
The DNS `resolver` is the server actually contacted, when observable; it is
neither the queried hostname nor the IP returned in an answer. HTTP `final_url`
is the final response reached under the producer's redirect behavior. Its method
belongs to that final request, which can differ from the initial request.

`ProbeLocation` is declared geography. `NetworkContext.country_code` and origin
ASN describe the outward-facing probe network at measurement time, not the
target network. IP-derived country attribution does not prove physical location.
Country codes use two uppercase ASCII letters from ISO 3166-1; the harness checks
the shape rather than embedding a changing country registry.

Optional deployment, software, location, ASN attribution, and addresses may be
omitted. Unless a field explicitly defines more states, absence means “no claim”:
unknown, not observed, not applicable, or withheld are not distinguishable.
Consumers must not infer a reason. There is no requirement to collect metadata
just to populate these fields.

Externally observed IPs, local socket addresses, probe identifiers, location,
URLs/queries, HTTP headers and bodies, SNI, certificates, and error detail can
contain sensitive information. Collection and disclosure policy belongs to
runtime components. Omit optional observations when policy requires it; a private
socket address must not be substituted for an unknown external address. A producer
must not claim COMPLETE body capture after redacting bytes; it can disable body
capture instead. PARTIAL does not mean optional metadata was intentionally withheld.

## Timing

Envelope timestamps are UTC wall-clock execution bounds, not ingestion or storage
times. Both are required and `finished_at >= started_at`, at nanosecond precision.
Equality is valid. Clock correction must be handled by the producer without
emitting inverted bounds; no particular clock synchronization implementation is
prescribed.

Result durations are non-negative observations of their named operations. Zero
is meaningful; absent is not measured zero. Producers should use a monotonic
clock for elapsed time. Do not require elapsed to equal wall-clock subtraction:
the operation boundaries differ, and wall clocks can be corrected. Failed
executions still have envelope bounds without a successful result duration.

HTTP `elapsed` remains time through completion of the final response body,
including followed redirects. When body reception fails, omit it; do not change
its meaning to time-to-failure. The envelope records when the partial execution
ended. Intentionally limiting retained bytes can still be SUCCEEDED if the
transaction completes and its full elapsed time is observed.

## HTTP body capture

`body` contains bytes after HTTP transfer framing/codings are removed, while
content codings such as gzip remain. `body_capture` describes retained bytes,
independently of execution status:

| Capture state | Meaning |
| --- | --- |
| UNSPECIFIED | Completeness was not reported; valid for older producers |
| COMPLETE | Entire body retained; empty means a complete empty body |
| TRUNCATED | Only a prefix retained, possibly empty; omission may be intentional or caused by a failure |
| NOT_CAPTURED | Capture intentionally disabled; body must be empty |

Producers should report capture state when known. Consumers must not infer
COMPLETE from non-empty bytes, SUCCEEDED, or an absent/default capture state.
For a known interrupted body transfer, use TRUNCATED, PARTIAL, and an error;
for a successful transaction with a retention limit, TRUNCATED and SUCCEEDED
can coexist. These distinctions do not impose a body-collection policy.

Optional `body_size` is the total size actually observed in the same encoding as
`body`; it is not an advertised Content-Length. Omit it if the full size was not
observed. With COMPLETE it equals the decoded byte length, and with TRUNCATED
it must be larger when known. Captured length is already derivable, so there is
no redundant `captured_body_size`. An explicitly present size of zero differs
from an absent size.

Only the final response is represented. Duplicate HTTP header field values are
preserved as separate entries; do not combine Set-Cookie values. Header field
name casing is not canonical. The relative ordering of different header field
names is not semantically significant and consumers MUST NOT rely on
cross-header wire-order preservation. Producers may retain the order supplied
by their HTTP library, but that order is not a protocol guarantee. Redirect
history, interim responses, trailers, and raw packet capture are outside this
result. No redirect-following policy is mandated.

## DNS and TLS boundaries

DNS describes one IN query/response exchange, not a resolver's full recursive
process. The answer section preserves CNAMEs and other answer records in order.
`response_truncated` is the observed TC bit: absent is unknown, present false is
explicitly not truncated. A fully received response with TC set can be SUCCEEDED;
TC does not mean the probe timed out. Do not silently flatten retry/fallback
exchanges into one timing or imply that a limited answer view is complete.

Authority/additional sections, other flags, raw packets, EDNS options beyond the
extended RCODE, and richer DNS provenance can be added later. Missing authority
data means this result alone cannot prove an authenticated negative answer.

TLS reports negotiated parameters and any retained peer-supplied DER certificates,
leaf first, without adding a locally constructed chain or trust roots. A result
does not assert certificate trust, hostname validation, or a validation policy.
An empty certificate list means none were recorded; it does not prove none were
sent (for example a resumed or PSK handshake may supply none).

Certificates or alerts seen before a failed TLS handshake cannot currently be
reported as a `TlsHandshakeResult`. That limitation is deliberate: a future
additive failure-observation field would need its own explicit completion and
presence rules. This release does not reinterpret a successful handshake result
as an incomplete one.

## Forward compatibility and validation

There are three distinct levels:

1. Protobuf-decodable: the binary field stream can be parsed.
2. Schema-valid: recognized fields can be decoded using these descriptors and
   protobuf types (including well-known type conversion). Unknown binary fields
   and open enum numbers can survive this level. ProtoJSON parsers may reject or
   discard unknown field names; it is not the transparent forwarding format.
3. Semantically valid GIO: understood fields meet the cross-message rules above.

A schema-valid message can violate known GIO rules. A future enum number is a
different case: it is decodable but its semantics may be unsupported, rather
than malformed or equivalent to UNSPECIFIED. Consumers may defer interpretation,
route it to a newer reader, or record an explicit unsupported outcome. They must
not fabricate a known kind/status or falsely certify it as understood.

When a future kind introduces a result member, an old reader can see the kind's
unknown number with no recognized result. It must not misclassify that absence
as a broken SUCCEEDED relationship for a known kind. Adding a new member must
also define its kind/status behavior. Protobuf `oneof` parsing keeps the last
distinct recognized member on the wire; repeated occurrences of the same
message member merge subfields. Producers emit one intended member.

Forward exact opaque protobuf bytes when transparent preservation is required.
Unknown-field retention depends on runtime and processing path; JSON conversion
or rebuilding a message from known fields can discard data. The harness checks
Buf's dynamic binary conversion specifically, not every consumer implementation.

## Pre-release audit decisions

The audit retains every existing field number, enum value, package, file, and
`oneof` membership. Additions are `HttpBodyCapture`, HTTP fields 7/8, DNS field 8,
and `MeasurementErrorCode.OTHER = 10`. Missing new fields retain unknown semantics
so older records remain readable. Buf's `FILE` compatibility policy is unchanged.

Before the first release, the ambiguous description of HTTP as always “completed”
is clarified to permit a useful response prefix under the existing PARTIAL
envelope. Its successful elapsed field retains its original completion meaning
and becomes optional only for partial responses. Old harness versions required
that field for every HTTP result and will reject this newly supported case;
consumers should adopt the audited release's semantic rules. DNS's previously
implicit Internet class and protocol numeric ranges are made explicit. No
existing wire field is repurposed, and no breaking-check exception is used.

Broader result capture, root-name/non-IN DNS extensions, TLS failure observations,
redirect history, and new measurement families are deferred. Repository release
`v0.1.0` identifies a source revision; `.v1` is the independent protocol API major
version. Consumers pin the Git revision/tag and generate bindings themselves.
