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

When a field is removed, reserve both its number and name whenever possible:

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

## Semantic compatibility

Automated wire checks cannot detect every semantic break. Reviewers must reject changes that preserve the wire representation but materially alter the meaning, units, lifecycle, or interpretation of an existing field.
