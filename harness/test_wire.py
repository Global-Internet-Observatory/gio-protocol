"""Focused protobuf evolution experiments; imported only by the internal harness."""

from copy import deepcopy
import json


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run_wire_tests(codec, fixtures, validate, expect_error, unsupported, wire_error):
    def fixture(name):
        return json.loads((fixtures / "valid" / name).read_text(encoding="utf-8"))

    tcp = fixture("minimal_tcp_connect.json")
    dns = fixture("successful_dns.json")
    http = fixture("successful_http.json")
    cases = 0

    # Derive a synthetic future descriptor in the system temporary directory.
    # The marker and result are TEST-ONLY fields, not allocations in GIO's schema.
    descriptor = json.loads(codec.schema.read_text(encoding="utf-8"))
    file = next(f for f in descriptor["file"] if f["name"] == "gio/measurement/v1/measurement.proto")
    measurement = next(m for m in file["messageType"] if m["name"] == "Measurement")
    check(not {1000, 1001} & {f["number"] for f in measurement["field"]}, "test field collision")
    measurement["field"].extend([
        {"name": "future_result", "jsonName": "futureResult", "number": 1001,
         "label": "LABEL_OPTIONAL", "type": "TYPE_MESSAGE", "typeName": ".gio.measurement.v1.DnsResult",
         "oneofIndex": next(i for i, o in enumerate(measurement["oneofDecl"]) if o["name"] == "result")},
        {"name": "evolution_marker", "jsonName": "evolutionMarker", "number": 1000,
         "label": "LABEL_OPTIONAL", "type": "TYPE_STRING"},
    ])
    future = codec.directory / "future.json"
    future.write_text(json.dumps(descriptor), encoding="utf-8")

    newer = dict(tcp, evolutionMarker="test-only future data")
    payload = codec.encode(newer, future)
    older_view = codec.decode(payload)
    check(older_view == codec.round_trip(tcp), "unknown field affected known fields")
    validate(older_view)
    check(codec.decode(payload, future)["evolutionMarker"] == newer["evolutionMarker"], "opaque bytes lost data")
    cases += 1

    # This explicitly tests Buf's current dynamic binary converter, not all GIO
    # runtimes and not arbitrary decode/modify/reencode forwarding pipelines.
    forwarded = codec.convert(payload, "binpb", "binpb")
    check(codec.decode(forwarded, future)["evolutionMarker"] == newer["evolutionMarker"],
          "Buf binary conversion no longer preserves unknown fields; review the documented guarantee")
    json_bridge = codec.encode(older_view)
    check("evolutionMarker" not in codec.decode(json_bridge, future), "expected JSON bridge to drop unknown field")
    cases += 1

    newer_result = deepcopy(dns)
    newer_result["kind"] = 1000
    newer_result["futureResult"] = newer_result.pop("dnsResult")
    decoded = codec.decode(codec.encode(newer_result, future))
    check(decoded["kind"] == 1000 and not any(k.endswith("Result") for k in decoded),
          "old reader must see unknown kind and no recognized result")
    try:
        validate(decoded)
    except unsupported:
        pass
    else:
        raise AssertionError("unknown kind/result must require newer semantics")
    cases += 1

    # Proto3 preserves unknown positive and negative enum numbers on the wire.
    enum_examples = [
        (tcp, ("kind",), 1000),
        (tcp, ("status",), 1000),
        (fixture("failed_http.json"), ("errors", 0, "code"), 1000),
        (dns, ("dnsResult", "transport"), 1000),
        (http, ("httpResult", "bodyCapture"), 1000),
        (tcp, ("kind",), -7),
    ]
    for source, path, number in enum_examples:
        message = deepcopy(source)
        parent = message
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = number
        decoded = codec.round_trip(message)
        observed = decoded
        for key in path:
            observed = observed[key]
        check(observed == number, f"unknown enum number lost at {path}")
        try:
            validate(decoded)
        except unsupported:
            pass
        else:
            raise AssertionError(f"future enum {path} was incorrectly treated as understood")
        cases += 1

    # Default-valued optional fields retain presence across real binary encoding.
    absent = deepcopy(dns)
    absent["dnsResult"].pop("responseCode")
    decoded_absent = codec.round_trip(absent)
    decoded_zero = codec.round_trip(dns)
    check("responseCode" not in decoded_absent["dnsResult"], "absent RCODE became present")
    check(decoded_zero["dnsResult"]["responseCode"] == 0, "present NOERROR was lost")
    expect_error(decoded_absent, "dns_rcode")
    validate(decoded_zero)
    cases += 1

    absent = deepcopy(dns)
    absent["dnsResult"].pop("responseTruncated", None)
    explicit = deepcopy(absent)
    explicit["dnsResult"]["responseTruncated"] = False
    check("responseTruncated" not in codec.round_trip(absent)["dnsResult"], "absent TC became false")
    check(codec.round_trip(explicit)["dnsResult"].get("responseTruncated") is False, "explicit false TC lost")
    validate(codec.round_trip(absent))
    validate(codec.round_trip(explicit))
    cases += 1

    empty = fixture("empty_http_body.json")
    absent = deepcopy(empty)
    absent["httpResult"].pop("bodySize")
    check("bodySize" not in codec.round_trip(absent)["httpResult"], "unknown body size became zero")
    check(codec.round_trip(empty)["httpResult"]["bodySize"] == "0", "observed zero body size lost")
    validate(codec.round_trip(absent))
    cases += 1

    # Existing HTTP records without the new capture metadata stay understood;
    # absent completeness is unknown, never an implicit COMPLETE assertion.
    legacy = deepcopy(http)
    legacy["httpResult"].pop("bodyCapture")
    legacy["httpResult"].pop("bodySize")
    validate(codec.round_trip(legacy))
    cases += 1

    # Negative protocol responses are successful observations, not execution errors.
    negative_dns = deepcopy(dns)
    negative_dns["dnsResult"]["responseCode"] = 3
    negative_dns["dnsResult"]["answers"] = []
    validate(codec.round_trip(negative_dns))
    negative_http = deepcopy(http)
    negative_http["httpResult"]["statusCode"] = 500
    validate(codec.round_trip(negative_http))
    cases += 1

    fallback = fixture("failed_http.json")
    fallback["errors"][0]["code"] = "MEASUREMENT_ERROR_CODE_OTHER"
    validate(codec.round_trip(fallback))
    cases += 1

    # HTTP duplicate values remain separate entries, but cross-name ordering is
    # not a semantic invariant. Both permutations must remain valid without a
    # sorting or normalization requirement in the harness.
    headers = [
        {"name": "X-A", "value": "MQ=="},
        {"name": "X-B", "value": "Mg=="},
        {"name": "Set-Cookie", "value": "YT0x"},
        {"name": "Set-Cookie", "value": "Yj0y"},
    ]
    reordered_headers = [headers[2], headers[1], headers[0], headers[3]]

    def header_value_counts(value):
        counts = {}
        for header in value["httpResult"]["responseHeaders"]:
            key = (header["name"].lower(), header["value"])
            counts[key] = counts.get(key, 0) + 1
        return counts

    expected_headers = {
        ("x-a", "MQ=="): 1,
        ("x-b", "Mg=="): 1,
        ("set-cookie", "YT0x"): 1,
        ("set-cookie", "Yj0y"): 1,
    }
    for candidate_headers in (headers, reordered_headers):
        candidate = deepcopy(http)
        candidate["httpResult"]["responseHeaders"] = candidate_headers
        decoded = codec.round_trip(candidate)
        validate(decoded)
        check(header_value_counts(decoded) == expected_headers,
              "duplicate HTTP header values were merged, omitted, or changed")
    cases += 1

    # Header names remain subject to the HTTP token/non-empty semantic checks;
    # header ordering is the only behavior relaxed by this change.
    for name, rule in (("", "required_value"), ("invalid header", "http_header")):
        candidate = deepcopy(http)
        candidate["httpResult"]["responseHeaders"] = [{"name": name, "value": "MQ=="}]
        expect_error(codec.round_trip(candidate), rule)
        cases += 1

    # Deliberately concatenate separately encoded result fields. This tests binary
    # oneof parsing, not JSON's refusal to accept two members at once.
    envelope = {k: v for k, v in tcp.items() if k != "tcpConnectResult"}
    envelope_wire = codec.encode(envelope)
    tcp_wire = codec.encode({"tcpConnectResult": tcp["tcpConnectResult"]})
    dns_wire = codec.encode({"dnsResult": dns["dnsResult"]})
    decoded = codec.decode(envelope_wire + tcp_wire + dns_wire)
    check("dnsResult" in decoded and "tcpConnectResult" not in decoded, "last distinct oneof member did not win")
    expect_error(decoded, "kind_result")
    decoded = codec.decode(envelope_wire + dns_wire + tcp_wire)
    check("tcpConnectResult" in decoded and "dnsResult" not in decoded, "reverse oneof order failed")
    validate(decoded)
    cases += 1

    # Repeated occurrences of the SAME message-valued member merge subfields.
    endpoint_only = {"tcpConnectResult": {"remoteEndpoint": tcp["tcpConnectResult"]["remoteEndpoint"]}}
    elapsed_only = {"tcpConnectResult": {"elapsed": "0s"}}
    decoded = codec.decode(envelope_wire + codec.encode(endpoint_only) + codec.encode(elapsed_only))
    check(decoded == codec.round_trip(tcp), "same oneof member did not merge")
    validate(decoded)
    cases += 1

    # A missing Duration is not a measured zero Duration.
    missing_elapsed = deepcopy(tcp)
    missing_elapsed["tcpConnectResult"].pop("elapsed")
    expect_error(codec.round_trip(missing_elapsed), "duration")
    validate(codec.round_trip(tcp))
    cases += 1

    # Buf's JSON parser discards unknown names. The fixture wrapper rejects them
    # using the descriptor, so fixture typos cannot silently disappear.
    dropped = codec.convert(b'{"unknownJsonName": true}', "json", "binpb")
    check(codec.decode(dropped) == {}, "review Buf's changed JSON unknown-field behavior")
    cases += 1

    # Malformed wire, wrong known-field types, and fixture field-name mistakes
    # fail before GIO semantic validation.
    for convert in (
        lambda: codec.decode(b"\x0a\x05x"),  # field 1 claims five bytes, only one follows
        lambda: codec.encode(dict(tcp, unrecognizedJsonField=True)),
        lambda: codec.encode({"probe": {"typoProbeId": "probe-example"}}),
        lambda: codec.encode({"measurementId": []}),
    ):
        try:
            convert()
        except wire_error:
            pass
        else:
            raise AssertionError("malformed wire or unknown JSON field unexpectedly accepted")
        cases += 1

    return cases
