#!/usr/bin/env python3
"""Repository-internal checks of decoded Measurement v1 semantics, using Buf."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from test_wire import run_wire_tests


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "harness" / "fixtures"
MESSAGE_TYPE = "gio.measurement.v1.Measurement"
RESULT_FOR_KIND = {
    "MEASUREMENT_KIND_DNS": "dnsResult",
    "MEASUREMENT_KIND_HTTP": "httpResult",
    "MEASUREMENT_KIND_TCP_CONNECT": "tcpConnectResult",
    "MEASUREMENT_KIND_TLS_HANDSHAKE": "tlsHandshakeResult",
}
RESULT_FIELDS = set(RESULT_FOR_KIND.values())
STATUSES = {"EXECUTION_STATUS_" + name for name in ("SUCCEEDED", "FAILED", "PARTIAL")}
ERROR_CODES = {"MEASUREMENT_ERROR_CODE_" + name for name in (
    "CANCELLED", "TIMEOUT", "DNS_RESOLUTION_FAILED", "NETWORK_UNREACHABLE",
    "CONNECTION_REFUSED", "CONNECTION_RESET", "TLS_HANDSHAKE_FAILED",
    "PROTOCOL_ERROR", "INTERNAL_ERROR", "OTHER",
)}
DNS_TRANSPORTS = {"DNS_TRANSPORT_" + name for name in ("UDP", "TCP", "TLS", "HTTPS")}
BODY_CAPTURES = {"HTTP_BODY_CAPTURE_" + name for name in (
    "UNSPECIFIED", "COMPLETE", "TRUNCATED", "NOT_CAPTURED",
)}
COUNTRY_CODE = re.compile(r"[A-Z]{2}")
TIMESTAMP = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z")
DURATION = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,9})?s")


class ConformanceError(ValueError):
    """Schema-decodable data violates a known GIO invariant (not protobuf syntax)."""

    def __init__(self, rule, message):
        self.rule = rule
        super().__init__(f"{rule}: {message}")


class UnsupportedSemantics(ValueError):
    """A wire-decodable enum value requires semantics this reader does not know."""


class WireError(ValueError):
    """Buf failed to build or convert a message; never an expected semantic failure."""


def require(condition, rule, message):
    if not condition:
        raise ConformanceError(rule, message)


def nonempty_string(value, field):
    require(isinstance(value, str) and bool(value), "required_value", f"{field} must be non-empty")
    return value


def known_enum(value, names, field):
    # Buf renders known values as names and unrecognized values as integers.
    # Zero/default is an invalid GIO sentinel, not an unknown future value.
    require(value not in (None, 0) and not str(value).endswith("_UNSPECIFIED"),
            "unspecified_enum", f"{field} must be specified")
    if value not in names:
        raise UnsupportedSemantics(f"{field}: unrecognized value {value!r}")
    return value


def positive_port(value, field):
    require(isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535,
            "endpoint_port", f"{field} must be from 1 through 65535")


def validate_ip_address(value, field):
    require(isinstance(value, dict), "ip_length", f"{field} is required")
    # Buf already checked the JSON bytes representation; inspect decoded octet count.
    address = base64.b64decode(value.get("address", ""), validate=True)
    require(len(address) in (4, 16), "ip_length", f"{field} must contain 4 or 16 bytes")


def validate_endpoint(value, field):
    require(isinstance(value, dict), "required_value", f"{field} is required")
    validate_ip_address(value.get("ipAddress"), f"{field}.ipAddress")
    positive_port(value.get("port", 0), f"{field}.port")


def parse_timestamp(value, field):
    # Only normalized ProtoJSON from Buf enters semantic validation. Its decoder
    # checks Timestamp ranges/calendar validity. Preserve all nine fractional digits.
    match = TIMESTAMP.fullmatch(nonempty_string(value, field))
    require(match is not None, "timestamp", f"{field} must be a normalized Timestamp")
    return match[1], int((match[2] or "").ljust(9, "0"))


def validate_duration(value, field):
    require(isinstance(value, str) and DURATION.fullmatch(value) is not None,
            "duration", f"{field} must be a present, non-negative Duration")


def validate_country_code(value, field):
    if value is not None:
        require(isinstance(value, str) and COUNTRY_CODE.fullmatch(value) is not None,
                "country_code", f"{field} must contain two uppercase ASCII letters")


def validate_absolute_url(value, field, schemes=()):
    nonempty_string(value, field)
    try:
        parsed = urlsplit(value)
        valid = bool(parsed.scheme and parsed.netloc and parsed.hostname)
        port = parsed.port  # Also reject malformed/out-of-range URL ports.
        valid = valid and (port is None or port > 0)
        valid = valid and not any(char.isspace() for char in value)
    except ValueError:
        valid = False
    require(valid, "url", f"{field} must be an absolute URL with an authority")
    require(not schemes or parsed.scheme.lower() in schemes,
            "url", f"{field} must use one of {schemes}")


def validate_probe(value):
    require(isinstance(value, dict), "required_value", "probe is required")
    nonempty_string(value.get("probeId"), "probe.probeId")
    if "location" in value:
        validate_country_code(value["location"].get("countryCode"), "probe.location.countryCode")


def validate_network(value):
    if "autonomousSystemNumber" in value:
        require(value["autonomousSystemNumber"] > 0, "asn", "origin ASN cannot be zero")
    validate_country_code(value.get("countryCode"), "network.countryCode")
    if "observedIpAddress" in value:
        validate_ip_address(value["observedIpAddress"], "network.observedIpAddress")


def validate_target(value):
    require(isinstance(value, dict) and any(value.get(f) for f in ("hostname", "ipAddress", "url")),
            "target", "target must contain a hostname, IP address, or URL")
    if "hostname" in value:
        hostname = nonempty_string(value["hostname"], "target.hostname")
        require(not hostname.endswith("."), "target", "hostname must not have a trailing root dot")
    if "ipAddress" in value:
        validate_ip_address(value["ipAddress"], "target.ipAddress")
    if "port" in value:
        positive_port(value["port"], "target.port")
    if "url" in value:
        validate_absolute_url(value["url"], "target.url")


def validate_dns(value, status):
    name = nonempty_string(value.get("queryName"), "dnsResult.queryName")
    require(not name.endswith("."), "dns_name", "queryName must not have a trailing root dot")
    require(1 <= value.get("queryType", 0) <= 65535, "dns_type", "QTYPE must be 1 through 65535")
    require("responseCode" in value and 0 <= value["responseCode"] <= 4095,
            "dns_rcode", "a usable DNS response requires an RCODE in 0 through 4095")
    known_enum(value.get("transport"), DNS_TRANSPORTS, "dnsResult.transport")
    if "resolver" in value:
        validate_endpoint(value["resolver"], "dnsResult.resolver")
    for answer in value.get("answers", []):
        nonempty_string(answer.get("name"), "dnsResult.answers.name")
        require(1 <= answer.get("type", 0) <= 65535, "dns_type", "RR TYPE must be 1 through 65535")
        # RDATA text depends on TYPE. Do not implement a second DNS parser here.
    validate_duration(value.get("elapsed"), "dnsResult.elapsed")


def validate_http(value, status):
    method = nonempty_string(value.get("method"), "httpResult.method")
    require(re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Z-]+", method) is not None,
            "http_method", "method must be an uppercase HTTP token")
    validate_absolute_url(value.get("finalUrl"), "httpResult.finalUrl", ("http", "https"))
    require(100 <= value.get("statusCode", 0) <= 599, "http_status", "statusCode must be 100 through 599")
    for header in value.get("responseHeaders", []):
        name = nonempty_string(header.get("name"), "httpResult.responseHeaders.name")
        require(re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) is not None,
                "http_header", "header name must be an HTTP token")
    if status == "EXECUTION_STATUS_SUCCEEDED" or "elapsed" in value:
        validate_duration(value.get("elapsed"), "httpResult.elapsed")
    capture = value.get("bodyCapture", "HTTP_BODY_CAPTURE_UNSPECIFIED")
    if capture not in BODY_CAPTURES:
        raise UnsupportedSemantics(f"httpResult.bodyCapture: unrecognized value {capture!r}")
    captured = len(base64.b64decode(value.get("body", ""), validate=True))
    size = int(value["bodySize"]) if "bodySize" in value else None
    require(size is None or size >= captured, "http_body_size", "bodySize cannot be smaller than body")
    if capture == "HTTP_BODY_CAPTURE_COMPLETE":
        require(size is None or size == captured, "http_body_size", "complete bodySize must equal body length")
    elif capture == "HTTP_BODY_CAPTURE_TRUNCATED":
        require(size is None or size > captured, "http_body_size", "truncated bodySize must exceed body length")
    elif capture == "HTTP_BODY_CAPTURE_NOT_CAPTURED":
        require(captured == 0, "http_body_capture", "uncaptured body must be empty")


def validate_tcp(value, status):
    validate_endpoint(value.get("remoteEndpoint"), "tcpConnectResult.remoteEndpoint")
    if "localEndpoint" in value:
        validate_endpoint(value["localEndpoint"], "tcpConnectResult.localEndpoint")
    validate_duration(value.get("elapsed"), "tcpConnectResult.elapsed")


def validate_tls(value, status):
    validate_endpoint(value.get("remoteEndpoint"), "tlsHandshakeResult.remoteEndpoint")
    if "serverName" in value:
        nonempty_string(value["serverName"], "tlsHandshakeResult.serverName")
    nonempty_string(value.get("protocolVersion"), "tlsHandshakeResult.protocolVersion")
    nonempty_string(value.get("cipherSuite"), "tlsHandshakeResult.cipherSuite")
    for certificate in value.get("peerCertificates", []):
        require(bool(base64.b64decode(certificate, validate=True)), "tls_certificate", "DER certificate cannot be empty")
    # Certificate parsing, chain building and trust policy are not harness dependencies.
    validate_duration(value.get("elapsed"), "tlsHandshakeResult.elapsed")


RESULT_VALIDATORS = {
    "dnsResult": validate_dns,
    "httpResult": validate_http,
    "tcpConnectResult": validate_tcp,
    "tlsHandshakeResult": validate_tls,
}


def validate_measurement(value):
    """Accept normalized, schema-decoded ProtoJSON; raise separately for unknown semantics."""
    nonempty_string(value.get("measurementId"), "measurementId")
    kind = known_enum(value.get("kind"), RESULT_FOR_KIND, "kind")
    status = known_enum(value.get("status"), STATUSES, "status")
    started = parse_timestamp(value.get("startedAt"), "startedAt")
    finished = parse_timestamp(value.get("finishedAt"), "finishedAt")
    require(finished >= started, "timestamp_order", "finishedAt must not precede startedAt")
    validate_probe(value.get("probe"))
    if "network" in value:
        validate_network(value["network"])
    validate_target(value.get("target"))
    errors = value.get("errors", [])
    for error in errors:
        known_enum(error.get("code"), ERROR_CODES, "errors.code")
    results = [field for field in RESULT_FIELDS if field in value]
    require(len(results) <= 1, "oneof", "only one decoded result is permitted")
    result = results[0] if results else None
    if status == "EXECUTION_STATUS_SUCCEEDED":
        require(result is not None and not errors, "status_result", "SUCCEEDED requires a result and no errors")
    elif status == "EXECUTION_STATUS_FAILED":
        require(result is None and bool(errors), "status_result", "FAILED requires errors and no result")
    else:
        require(result is not None and bool(errors), "status_result", "PARTIAL requires a result and errors")
    if result is not None:
        require(result == RESULT_FOR_KIND[kind], "kind_result", f"{kind} requires {RESULT_FOR_KIND[kind]}")
        RESULT_VALIDATORS[result](value[result], status)


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WireError(f"duplicate fixture JSON field: {key}")
        result[key] = value
    return result


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)


class BufCodec:
    """Dynamic conversion using temporary descriptors; no generated language APIs."""

    def __init__(self, executable, directory, message_type=MESSAGE_TYPE):
        self.executable = executable
        self.directory = directory
        self.message_type = message_type
        self.schema = directory / "schema.json"
        self.run("build", str(ROOT), "--as-file-descriptor-set", "--exclude-source-info",
                 "-o", str(self.schema))

    def run(self, *arguments, payload=None):
        process = subprocess.run([self.executable, *arguments], input=payload,
                                 capture_output=True, cwd=ROOT)
        if process.returncode:
            raise WireError(process.stderr.decode("utf-8", errors="replace").strip())
        return process.stdout

    def convert(self, payload, source, destination, schema=None):
        return self.run("convert", str(schema or self.schema), "--type", self.message_type,
                        "--from", f"-#format={source}", "--to", f"-#format={destination}", payload=payload)

    def encode(self, value, schema=None):
        # Buf convert discards unknown JSON keys. Reject fixture typos using the
        # descriptor, without duplicating protobuf's type or wire validation.
        descriptor = load_json(schema or self.schema)
        messages = {f".{file['package']}.{message['name']}": message
                    for file in descriptor["file"] for message in file.get("messageType", [])}

        def check_names(message, type_name):
            if not isinstance(message, dict) or type_name not in messages:
                return
            fields = {name: field for field in messages[type_name].get("field", [])
                      for name in (field["name"], field.get("jsonName", field["name"]))}
            for name, item in message.items():
                if name not in fields:
                    raise WireError(f"unknown fixture field {type_name}.{name}")
                field = fields[name]
                if field["type"] == "TYPE_MESSAGE":
                    for child in item if isinstance(item, list) else [item]:
                        check_names(child, field["typeName"])

        check_names(value, "." + self.message_type)
        return self.convert(json.dumps(value).encode(), "json", "binpb", schema)

    def decode(self, payload, schema=None):
        return json.loads(self.convert(payload, "binpb", "json", schema))

    def round_trip(self, value):
        decoded = self.decode(self.encode(value))
        if decoded != self.decode(self.encode(decoded)):
            raise WireError("decoded message changed meaning after a wire round trip")
        return decoded


def expect_semantic_error(value, rule):
    try:
        validate_measurement(value)
    except ConformanceError as error:
        if error.rule != rule:
            raise AssertionError(f"expected {rule}, got {error}") from error
    else:
        raise AssertionError(f"expected semantic violation {rule}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--buf", default=os.environ.get("BUF", "buf"))
    arguments = parser.parse_args()
    valid = sorted((FIXTURES / "valid").glob("*.json"))
    invalid = sorted((FIXTURES / "invalid").glob("*.json"))
    expected = load_json(FIXTURES / "expectations.json")
    if not valid or {p.name for p in invalid} != set(expected):
        raise AssertionError("fixtures missing or invalid fixture expectations out of sync")
    with tempfile.TemporaryDirectory(prefix="gio-protocol-") as directory:
        codec = BufCodec(arguments.buf, Path(directory))
        for fixture in valid:
            try:
                validate_measurement(codec.round_trip(load_json(fixture)))
            except (ConformanceError, UnsupportedSemantics, WireError) as error:
                raise AssertionError(f"{fixture.name}: {error}") from error
        for fixture in invalid:
            # Decoding and round-trip failures cannot pass as expected GIO failures.
            decoded = codec.round_trip(load_json(fixture))
            try:
                expect_semantic_error(decoded, expected[fixture.name])
            except AssertionError as error:
                raise AssertionError(f"{fixture.name}: {error}") from error
        wire_cases = run_wire_tests(codec, FIXTURES, validate_measurement,
                                    expect_semantic_error, UnsupportedSemantics, WireError)
        from test_ingestion import run_ingestion_tests
        from test_authentication import run_authentication_tests
        ingestion_request = BufCodec(arguments.buf, Path(directory),
                                     "gio.ingestion.v1.SubmitMeasurementsRequest")
        ingestion_response = BufCodec(arguments.buf, Path(directory),
                                      "gio.ingestion.v1.SubmitMeasurementsResponse")
        ingestion_cases = run_ingestion_tests(
            ingestion_request, ingestion_response, FIXTURES, codec
        )
        authentication_cases = run_authentication_tests(
            ingestion_request, FIXTURES, codec
        )
    print(f"Conformance passed: {len(valid)} valid, {len(invalid)} semantic-invalid fixtures; "
          f"{wire_cases} Measurement wire cases; {ingestion_cases} ingestion cases; "
          f"{authentication_cases} authentication cases")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, ConformanceError, UnsupportedSemantics, WireError, OSError, ValueError) as error:
        print(f"conformance error: {error}", file=sys.stderr)
        raise SystemExit(1)
