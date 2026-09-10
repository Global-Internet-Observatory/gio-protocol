# Protocol conformance harness

This is repository-internal test code, not an SDK, Python package, supported
consumer API, or runtime dependency. Run `make test` from the repository root;
`make check` includes it. `BUF` and `PYTHON` select alternative executables.
CI uses Buf 1.72.0. Python 3.8+ needs only its standard library.

Buf dynamically compiles and converts the real schema. A descriptor set and a
synthetic future descriptor live in a system temporary directory and are removed
after testing. No bindings are generated or committed. Tests do not contact
measurement targets or use a registry, SDK toolchain, or external service.

## Validation levels

1. **Protobuf-decodable:** a well-formed binary field stream can be parsed. Tests
   distinguish malformed wire bytes from valid protobuf with unusable GIO data.
2. **Schema-valid:** known fields conform to the descriptor's protobuf types and
   well-known-type conversion rules. Unknown binary fields and enum numbers are
   allowed. Buf's JSON converter drops unknown names; a descriptor-based fixture
   check rejects them before conversion so a fixture typo cannot disappear.
3. **GIO semantic validity:** the normalized decoded message obeys the
   [Measurement v1 contract](../proto/gio/measurement/v1/README.md). Missing
   required semantic fields, inverted timestamps, and invalid result/error
   combinations raise `ConformanceError`, with an identified rule. Unrecognized
   future enum values raise the separate `UnsupportedSemantics` outcome.

The harness is an executable contract sample, not a complete production
validator. It does not perform DNS RDATA parsing, certificate trust/chain
validation, identity uniqueness checks across observations, country-registry
lookups, or runtime collection policy. It compares timestamps at full protobuf
nanosecond precision. It does not equate operation duration with wall-clock
subtraction.

## Fixtures and semantic coverage

`fixtures/valid/` holds readable ProtoJSON messages covering DNS, HTTP, TCP,
TLS, failure, partial HTTP response, DNS TC, empty body, uncaptured body, and
capture-limited successful HTTP response. Documentation IPs and example names
are intentional. The TLS certificate is a synthetic self-signed example with
no retained private key; validity dates and trust have no conformance meaning.

`fixtures/invalid/` holds **schema-decodable messages with invalid GIO semantics**.
`fixtures/expectations.json` names the exact expected rule for each file. Coverage
includes all terminal-state combinations, mismatched kind/result, unspecified
enums, IP length, port range, empty target, country-code shape, nanosecond time
ordering, negative durations, and inconsistent HTTP capture metadata.

Every fixture encodes to binary, decodes, re-encodes, and compares decoded meaning.
The invalid fixture's decode/round-trip is outside the expected-error handler:
an unrelated parsing error or wrong invariant cannot make it pass. Equivalent
messages are not assumed to have byte-identical serialization.

## Binary evolution coverage

`test_wire.py` constructs a temporary future descriptor with test-only fields
1000/1001; these are not GIO field allocations. The tests demonstrate:

- an old descriptor decodes known fields from a future binary message;
- forwarding its opaque original bytes preserves all data;
- Buf 1.72.0's dynamic binary-to-binary converter preserves the tested unknown
  field, while a bridge through the old descriptor's JSON representation loses it;
- unknown kind, status, error, DNS transport, and HTTP capture enum numbers
  (including a negative enum number) round-trip but are semantically unsupported;
- an unknown future kind/result is not a known-kind missing-result violation;
- optional RCODE absent versus present zero, TC absent versus present false,
  and body size absent versus present zero remain distinct;
- concatenated binary result fields retain only the last distinct recognized
  `oneof` member, and repeated occurrences of the same message member merge;
- decoded mismatched kind/result is rejected by GIO semantic validation;
- zero elapsed differs from missing elapsed, older HTTP capture metadata remains
  readable, and negative DNS/HTTP responses can be successful observations.

This is evidence about the tested Buf runtime and paths. It does not promise
that other language runtimes or arbitrary decode/modify/reencode pipelines retain
unknown data. Transparent forwarding should pass through the original bytes.

## Reviewing and updating fixtures

Edit/add small JSON examples and update the expected rule for an invalid example,
then run `make test`. Tests never rewrite fixtures. The one malformed-wire case
is an explicit three-byte literal annotated in the test, not a generated golden.
No deterministic serialization or golden binary measurement files are required.

To replace the example certificate deliberately, generate a disposable self-signed
DER certificate, base64-encode the complete DER, and replace the JSON value in a
reviewed PR. For example, using an isolated temporary directory:

```bash
fixture_tmp=$(mktemp -d)
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
  -subj '/CN=example.com' -days 1 -set_serial 1 \
  -keyout "$fixture_tmp/key.pem" -outform DER -out "$fixture_tmp/cert.der"
openssl x509 -inform DER -in "$fixture_tmp/cert.der" -noout -text
openssl base64 -A -in "$fixture_tmp/cert.der"
unlink "$fixture_tmp/key.pem"
unlink "$fixture_tmp/cert.der"
rmdir "$fixture_tmp"
```

OpenSSL is only an optional fixture-authoring tool; normal checks do not need it.
Certificate bytes are expected to change during deliberate regeneration and are
not golden serialization output. Review the subject, certificate encoding, and
absence of private keys; do not silently regenerate in CI.

If exact-wire golden fixtures become necessary later, document their source,
deterministic requirements, regeneration command, and review procedure beside
them. Fixtures and temporary descriptors must never become published artifacts.
