"""Conformance checks for the ingestion v1 exact-byte envelope."""

import base64
from copy import deepcopy
import hashlib
import json


MESSAGE_FIXTURE = "successful_dns.json"
STATUS_STORED = "INGESTION_STATUS_STORED"
STATUS_ALREADY_STORED = "INGESTION_STATUS_ALREADY_STORED"
STATUS_RETRY = "INGESTION_STATUS_RETRY"
STATUS_REJECTED = "INGESTION_STATUS_REJECTED"
STATUSES = {STATUS_STORED, STATUS_ALREADY_STORED, STATUS_RETRY, STATUS_REJECTED}


class IngestionError(ValueError):
    """An ingestion envelope violates a protocol-level invariant."""


def require(condition, message):
    if not condition:
        raise IngestionError(message)


def decode_bytes(value, field):
    require(isinstance(value, str), f"{field} must be protobuf bytes")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as error:
        raise IngestionError(f"{field} is not valid base64") from error


def digest(payload):
    return hashlib.sha256(payload).digest()


def validate_upload(upload, measurement_codec):
    require(isinstance(upload, dict), "measurement upload must be an object")
    measurement_id = upload.get("measurementId")
    require(isinstance(measurement_id, str) and measurement_id, "measurement ID must be non-empty")
    payload = decode_bytes(upload.get("measurementBytes", ""), "measurementBytes")
    supplied_digest = decode_bytes(upload.get("payloadSha256", ""), "payloadSha256")
    require(len(supplied_digest) == 32, "payloadSha256 must contain exactly 32 bytes")
    try:
        measurement = measurement_codec.decode(payload)
    except ValueError as error:
        raise IngestionError("measurementBytes is not a valid Measurement protobuf") from error
    try:
        from test_conformance import validate_measurement
        validate_measurement(measurement)
    except ValueError as error:
        raise IngestionError("measurementBytes is not a valid Measurement v1 envelope") from error
    require(measurement.get("measurementId") == measurement_id,
            "wrapper measurementId differs from decoded Measurement.measurementId")
    require(supplied_digest == digest(payload), "payloadSha256 does not match measurementBytes")
    return measurement_id, payload, supplied_digest


def validate_request(request, measurement_codec):
    require(isinstance(request, dict), "request must be an object")
    records = request.get("measurements", [])
    require(isinstance(records, list) and records, "request must contain at least one measurement")
    validated = [validate_upload(record, measurement_codec) for record in records]
    ids = [record[0] for record in validated]
    require(len(ids) == len(set(ids)), "measurement IDs must be unique within a request")
    return validated


def validate_ack(ack, submitted):
    require(isinstance(ack, dict), "acknowledgement must be an object")
    measurement_id = ack.get("measurementId")
    require(measurement_id in submitted, "acknowledgement ID is not in the request")
    supplied_digest = decode_bytes(ack.get("payloadSha256", ""), "ack.payloadSha256")
    require(len(supplied_digest) == 32, "ack.payloadSha256 must contain exactly 32 bytes")
    require(supplied_digest == submitted[measurement_id], "ack digest does not match submitted payload")
    status = ack.get("status")
    require(status in STATUSES, "acknowledgement status must be specified and known")
    return measurement_id, supplied_digest, status


def validate_response(response, submitted_order):
    require(isinstance(response, dict), "response must be an object")
    acknowledgements = response.get("acknowledgements", [])
    require(isinstance(acknowledgements, list), "acknowledgements must be a list")
    submitted = dict(submitted_order)
    require(len(acknowledgements) == len(submitted_order), "response must contain exactly one ack per record")
    seen = set()
    for ack, (expected_id, _) in zip(acknowledgements, submitted_order):
        measurement_id, _, _ = validate_ack(ack, submitted)
        require(measurement_id not in seen, "duplicate acknowledgement ID")
        require(measurement_id == expected_id, "acknowledgements must preserve request order")
        seen.add(measurement_id)
    require(seen == set(submitted), "response contains a missing or extra acknowledgement")
    return acknowledgements


def removable_ids(response, submitted_order):
    # Validate the complete set before resolving any individual success.
    acks = validate_response(response, submitted_order)
    return [ack["measurementId"] for ack in acks
            if ack["status"] in (STATUS_STORED, STATUS_ALREADY_STORED)]


def validate_ownership_outcome(ack, payload, before, after):
    """Check durability snapshots, not a collector/storage implementation."""
    status = ack["status"]
    if before is not None:
        require(after == before, "existing durable identity binding must not be overwritten")
        if before == payload:
            require(status == STATUS_ALREADY_STORED, "exact retry must be ALREADY_STORED")
        else:
            require(status == STATUS_REJECTED, "identity conflict must be REJECTED")
            require(bool(ack.get("detail")), "identity conflict requires diagnostic detail")
    elif status == STATUS_STORED:
        require(after == payload, "STORED requires durable ownership of exact bytes")
    else:
        require(status in (STATUS_RETRY, STATUS_REJECTED) and after is None,
                "non-acceptance must not claim durable ownership")


def add_unknown_measurement_field(codec, fixture):
    descriptor = json.loads(codec.schema.read_text(encoding="utf-8"))
    file = next(f for f in descriptor["file"] if f["name"] == "gio/measurement/v1/measurement.proto")
    measurement = next(m for m in file["messageType"] if m["name"] == "Measurement")
    measurement["field"].append({
        "name": "ingestion_test_marker", "jsonName": "ingestionTestMarker",
        "number": 1002, "label": "LABEL_OPTIONAL", "type": "TYPE_STRING",
    })
    future = codec.directory / "ingestion-future.json"
    future.write_text(json.dumps(descriptor), encoding="utf-8")
    value = dict(fixture, ingestionTestMarker="opaque-test-field")
    return codec.encode(value, future)


def run_ingestion_tests(request_codec, response_codec, fixtures, measurement_codec):
    fixture = json.loads((fixtures / "valid" / MESSAGE_FIXTURE).read_text(encoding="utf-8"))
    payload = measurement_codec.encode(fixture)
    measurement_id = fixture["measurementId"]
    payload_digest = digest(payload)
    upload = {
        "measurementId": measurement_id,
        "measurementBytes": base64.b64encode(payload).decode(),
        "payloadSha256": base64.b64encode(payload_digest).decode(),
    }
    request = {"measurements": [upload]}
    submitted = [(measurement_id, payload_digest)]
    cases = 0

    def rejects(operation, expected):
        try:
            operation()
        except IngestionError as error:
            if expected not in str(error):
                raise AssertionError(f"expected {expected!r}, got {error}") from error
        else:
            raise AssertionError(f"expected rejection: {expected}")

    # A valid upload and request round-trip through the real ingestion schema.
    decoded_request = request_codec.round_trip(request)
    validate_request(decoded_request, measurement_codec)
    cases += 1

    # The wrapper validates decoded Measurement semantics and binds identity and bytes.
    invalid_uploads = [
        (dict(upload, measurementId=""), "ID must be non-empty"),
        (dict(upload, measurementId="other-id"), "wrapper measurementId differs"),
        (dict(upload, payloadSha256=base64.b64encode(b"short").decode()), "exactly 32 bytes"),
        (dict(upload, payloadSha256=base64.b64encode(b"x" * 32).decode()), "does not match measurementBytes"),
        (dict(upload, measurementBytes=base64.b64encode(b"\x0a\x05x").decode()), "not a valid Measurement protobuf"),
    ]
    for candidate, expected in invalid_uploads:
        # Outer protobuf decode/round-trip must succeed before the expected error.
        decoded = request_codec.round_trip({"measurements": [candidate]})["measurements"][0]
        rejects(lambda: validate_upload(decoded, measurement_codec), expected)
        cases += 1

    for invalid_measurement in ({"measurementId": measurement_id}, dict(fixture, kind=1000)):
        invalid_payload = measurement_codec.encode(invalid_measurement)
        invalid = dict(upload, measurementBytes=base64.b64encode(invalid_payload).decode(),
                       payloadSha256=base64.b64encode(digest(invalid_payload)).decode())
        rejects(lambda: validate_upload(invalid, measurement_codec), "not a valid Measurement v1 envelope")
        cases += 1

    # Unknown Measurement protobuf fields survive as opaque bytes in the envelope.
    unknown_payload = add_unknown_measurement_field(measurement_codec, fixture)
    unknown_id = fixture["measurementId"]
    unknown_upload = {
        "measurementId": unknown_id,
        "measurementBytes": base64.b64encode(unknown_payload).decode(),
        "payloadSha256": base64.b64encode(digest(unknown_payload)).decode(),
    }
    round_tripped = request_codec.decode(request_codec.encode({"measurements": [unknown_upload]}))
    require(round_tripped["measurements"][0]["measurementBytes"] == unknown_upload["measurementBytes"],
            "ingestion envelope changed opaque Measurement bytes")
    require(decode_bytes(round_tripped["measurements"][0]["measurementBytes"], "payload") == unknown_payload,
            "unknown fields did not survive byte for byte")
    validate_request(round_tripped, measurement_codec)
    cases += 1

    # Request cardinality and per-request identity constraints.
    for candidate, expected in (({}, "at least one"), ({"measurements": []}, "at least one"),
                                ({"measurements": [upload, upload]}, "unique within")):
        decoded = request_codec.round_trip(candidate)
        rejects(lambda: validate_request(decoded, measurement_codec), expected)
        cases += 1

    # Every status is valid when the ID and exact digest are valid; UNSPECIFIED is not.
    acknowledgements = []
    for status in (STATUS_STORED, STATUS_ALREADY_STORED, STATUS_RETRY, STATUS_REJECTED):
        acknowledgements.append({
            "measurementId": measurement_id,
            "payloadSha256": base64.b64encode(payload_digest).decode(),
            "status": status,
        })
        decoded = response_codec.round_trip({"acknowledgements": [acknowledgements[-1]]})
        validate_response(decoded, submitted)
        require(removable_ids(decoded, submitted) ==
                ([measurement_id] if status in (STATUS_STORED, STATUS_ALREADY_STORED) else []),
                "non-acceptance authorized removal")
        cases += 1
    for candidate, expected in [
        (dict(acknowledgements[0], status="INGESTION_STATUS_UNSPECIFIED"), "specified and known"),
        (dict(acknowledgements[0], status=1000), "specified and known"),
        (dict(acknowledgements[0], measurementId="wrong"), "ID is not in"),
        (dict(acknowledgements[0], payloadSha256=base64.b64encode(b"z" * 32).decode()), "digest does not match"),
        (dict(acknowledgements[0], payloadSha256=""), "exactly 32 bytes"),
        ({"acknowledgements": []}, "exactly one ack"),
        ({"acknowledgements": [acknowledgements[0], acknowledgements[0]]}, "exactly one ack"),
    ]:
        response = candidate if "acknowledgements" in candidate else {"acknowledgements": [candidate]}
        decoded = response_codec.round_trip(response)
        rejects(lambda: removable_ids(decoded, submitted), expected)
        cases += 1

    # Mixed outcomes are independent, and response order is request correlation.
    fixture_b = dict(fixture, measurementId="measurement-second")
    payload_b = measurement_codec.encode(fixture_b)
    digest_b = digest(payload_b)
    order = [(measurement_id, payload_digest), ("measurement-second", digest_b)]
    mixed = {"acknowledgements": [
        {"measurementId": measurement_id, "payloadSha256": base64.b64encode(payload_digest).decode(), "status": STATUS_STORED},
        {"measurementId": "measurement-second", "payloadSha256": base64.b64encode(digest_b).decode(), "status": STATUS_REJECTED},
    ]}
    validate_response(mixed, order)
    cases += 1
    rejects(lambda: validate_response({"acknowledgements": list(reversed(mixed["acknowledgements"]))}, order),
            "preserve request order")
    cases += 1
    rejects(lambda: validate_response({"acknowledgements": [mixed["acknowledgements"][0]] * 2}, order),
            "duplicate acknowledgement ID")
    cases += 1

    # Model the idempotency contract: exact retries are already stored; a
    # conflicting payload is rejected and never overwrites the original.
    validate_ownership_outcome(acknowledgements[0], payload, None, payload)
    cases += 1
    rejects(lambda: validate_ownership_outcome(acknowledgements[0], payload, None, None),
            "STORED requires durable ownership")
    cases += 1
    validate_ownership_outcome(acknowledgements[1], payload, payload, payload)
    cases += 1
    # Different valid wire bytes, including unknown fields, are not an exact retry.
    conflicting = digest(unknown_payload)
    require(conflicting != payload_digest, "conflict fixture unexpectedly matched")
    conflict_ack = {
        "measurementId": measurement_id,
        "payloadSha256": base64.b64encode(conflicting).decode(),
        "status": STATUS_REJECTED,
        "detail": "identity conflict",
    }
    validate_ack(conflict_ack, {measurement_id: conflicting})
    validate_ownership_outcome(conflict_ack, unknown_payload, payload, payload)
    rejects(lambda: validate_ownership_outcome(conflict_ack, unknown_payload, payload, unknown_payload),
            "must not be overwritten")
    rejects(lambda: validate_ownership_outcome(acknowledgements[1], unknown_payload, payload, payload),
            "identity conflict must be REJECTED")
    cases += 1

    # The codec itself must preserve the envelope wire representation.
    require(response_codec.decode(response_codec.encode(mixed)) == mixed,
            "ingestion protobuf round-trip changed meaning")
    cases += 1

    # Minimal checked-in ProtoJSON examples use the same schemas and validators.
    ingestion_fixtures = fixtures / "ingestion"
    valid_upload = json.loads((ingestion_fixtures / "valid_upload.json").read_text())
    validate_upload(request_codec.round_trip({"measurements": [valid_upload]})["measurements"][0],
                    measurement_codec)
    batch = request_codec.round_trip(json.loads((ingestion_fixtures / "multi_request.json").read_text()))
    validated = validate_request(batch, measurement_codec)
    batch_order = [(record_id, sha256) for record_id, _, sha256 in validated]
    response = response_codec.round_trip(json.loads((ingestion_fixtures / "mixed_response.json").read_text()))
    require(removable_ids(response, batch_order) == [batch_order[0][0], batch_order[1][0]],
            "mixed response must independently resolve only STORED and ALREADY_STORED")
    cases += 3
    return cases
