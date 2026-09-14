# Protocol schemas

This directory contains the canonical Protocol Buffers source files for GIO.

Schemas are organized by protobuf package and API major version. Published packages should use an explicit version suffix such as `v1`.

The initial packages are:

- `gio.common.v1` for shared probe and network context;
- `gio.measurement.v1` for the measurement envelope, targets, and typed results;
- `gio.ingestion.v1` for exact-byte Measurement transfer and durable ownership
  acknowledgements.
- `gio.control.v1` for Probe Registration and initial credential provisioning.

All current files explicitly use Protocol Buffers v3 syntax. Adding a different
syntax or edition requires a deliberate repository-wide compatibility review.

Do not place generated language bindings in this directory or elsewhere in this repository.
