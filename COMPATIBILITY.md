# Compatibility policy

This repository treats published protobuf schemas as long-lived wire contracts.

## Versioning model

Protocol API major versions live in protobuf package names, for example `gio.<domain>.v1`. Repository release versions are separate and are represented by Git tags.

A breaking protocol change requires a new protobuf API major version rather than an incompatible mutation of an existing package.

## Allowed changes within an existing API major version

Generally allowed changes include:

- adding new messages;
- adding new fields using previously unused field numbers;
- adding new enum values when consumers are expected to tolerate unknown values;
- adding new services or methods if services are introduced later.

All changes must still pass Buf breaking-change checks.

## Prohibited changes within an existing API major version

Do not:

- change or reuse an existing field number;
- reuse the name or number of a removed field;
- change a field to an incompatible type;
- change enum numeric values;
- change the protobuf package of a published type;
- move published declarations between files when that breaks generated APIs;
- change `oneof` membership in a way that changes existing semantics;
- silently redefine the semantic meaning of an existing field.

## Removing fields

When a field is removed, reserve both its number and name:

```proto
message Example {
  reserved 7;
  reserved "old_field";
}
```

Field numbers are protocol history. They are never recycled.

## Compatibility gate

Pull requests that change schemas must pass:

```bash
buf breaking --against '.git#branch=main'
```

The repository currently uses Buf's `FILE` breaking policy so that compatibility checks protect both protobuf wire compatibility and the generated-code API surface implied by file structure.

Measurement v1 is the repository's first schema baseline. The baseline check is
skipped only when the comparison target contains no `.proto` files; after the
initial schema reaches `main`, every subsequent schema change is compared with
that history.

## Semantic compatibility

Automated wire checks cannot detect every semantic break. Reviewers must reject changes that preserve the wire representation but materially alter the meaning, units, lifecycle, or interpretation of an existing field.

Adding a field must define what its absence means for older records. Never
reinterpret an absent/default value as proof that an observation was made.
The same discipline applies to enum additions and new `oneof` alternatives:
define the new kind/result relationship and how an old reader can decline
interpretation without claiming the protobuf payload is malformed.

Proto3 enums are open on the wire. Unrecognized numbers are not the zero
UNSPECIFIED sentinel and must not be coerced to a known value. Unknown kinds,
statuses, and result variants may require newer semantic validation.

Unknown-field preservation is runtime- and pipeline-dependent. Forward opaque
protobuf bytes when transparent forwarding requires preserving all data.
Conversion through JSON or rebuilding from known fields can discard unknown
fields. The harness demonstrates Buf's behavior, not a guarantee for every
consumer implementation. See the [Measurement v1 contract](proto/gio/measurement/v1/README.md)
for the cross-message rules and the recorded pre-release clarifications.

### Measurement v1 HTTP header ordering correction

The `response_headers` field remains a repeated `HttpHeader` field with the
same field number and wire representation. Duplicate values remain separate
entries. As a pre-production semantic correction, Measurement v1 does not
require producers to preserve the relative wire order of entries with different
header names, and consumers must not depend on that ordering. Existing
serialized messages remain valid and readable; this change relaxes a producer
obligation without changing protobuf compatibility. Exact raw HTTP header bytes,
framing, and transcript ordering remain outside this result.
