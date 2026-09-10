#!/usr/bin/env python3
"""Exercise JSON fixtures against the Measurement v1 wire contract."""

import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit


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
COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
DURATION = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,9})?s$")


class ConformanceError(ValueError):
    """A message violates a Measurement v1 semantic invariant."""


def fail(message: str) -> None:
    raise ConformanceError(message)


def nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{field} must be a non-empty string")
    return value


def positive_port(value: Any, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
        fail(f"{field} must be an integer from 1 through 65535")


def validate_ip_address(value: Any, field: str) -> None:
    if not isinstance(value, dict):
        fail(f"{field} must be an object")
    encoded = nonempty_string(value.get("address"), f"{field}.address")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        fail(f"{field}.address must be canonical base64")
    if len(decoded) not in (4, 16):
        fail(f"{field}.address must contain exactly 4 or 16 bytes")


def validate_endpoint(value: Any, field: str) -> None:
    if not isinstance(value, dict):
        fail(f"{field} must be an object")
    validate_ip_address(value.get("ipAddress"), f"{field}.ipAddress")
    positive_port(value.get("port"), f"{field}.port")


def parse_timestamp(value: Any, field: str) -> datetime:
    text = nonempty_string(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        fail(f"{field} must be an RFC 3339 timestamp")
    if parsed.tzinfo is None:
        fail(f"{field} must include a UTC offset")
    return parsed


def validate_duration(value: Any, field: str) -> None:
    text = nonempty_string(value, field)
    if not DURATION.fullmatch(text):
        fail(f"{field} must be a non-negative protobuf duration")


def validate_country_code(value: Any, field: str) -> None:
    if value is not None and (not isinstance(value, str) or not COUNTRY_CODE.fullmatch(value)):
        fail(f"{field} must be an uppercase ISO 3166-1 alpha-2 code")


def validate_absolute_url(value: Any, field: str, schemes: Iterable[str] = ()) -> None:
    text = nonempty_string(value, field)
    parsed = urlsplit(text)
    if not parsed.scheme or not parsed.netloc:
        fail(f"{field} must be an absolute URL with an authority")
    allowed = set(schemes)
    if allowed and parsed.scheme.lower() not in allowed:
        fail(f"{field} must use one of: {', '.join(sorted(allowed))}")


def validate_probe(value: Any) -> None:
    if not isinstance(value, dict):
        fail("probe must be an object")
    nonempty_string(value.get("probeId"), "probe.probeId")
    location = value.get("location")
    if location is not None:
        if not isinstance(location, dict):
            fail("probe.location must be an object")
        validate_country_code(location.get("countryCode"), "probe.location.countryCode")


def validate_network(value: Any) -> None:
    if not isinstance(value, dict):
        fail("network must be an object")
    asn = value.get("autonomousSystemNumber")
    if asn is not None and (not isinstance(asn, int) or isinstance(asn, bool) or asn < 1):
        fail("network.autonomousSystemNumber must be a positive integer")
    validate_country_code(value.get("countryCode"), "network.countryCode")
    address = value.get("observedIpAddress")
    if address is not None:
        validate_ip_address(address, "network.observedIpAddress")


def validate_target(value: Any) -> None:
    if not isinstance(value, dict):
        fail("target must be an object")
    if not any(value.get(field) for field in ("hostname", "ipAddress", "url")):
        fail("target must contain hostname, ipAddress, or url")
    if "hostname" in value:
        hostname = nonempty_string(value["hostname"], "target.hostname")
        if hostname.endswith("."):
            fail("target.hostname must not have a trailing root dot")
    if "ipAddress" in value:
        validate_ip_address(value["ipAddress"], "target.ipAddress")
    if "port" in value:
        positive_port(value["port"], "target.port")
    if "url" in value:
        validate_absolute_url(value["url"], "target.url")


def validate_error(value: Any, index: int) -> None:
    if not isinstance(value, dict):
        fail(f"errors[{index}] must be an object")
    code = value.get("code")
    if code in (None, 0, "MEASUREMENT_ERROR_CODE_UNSPECIFIED"):
        fail(f"errors[{index}].code must be specified")


def validate_dns(value: Any) -> None:
    if not isinstance(value, dict):
        fail("dnsResult must be an object")
    name = nonempty_string(value.get("queryName"), "dnsResult.queryName")
    if name.endswith("."):
        fail("dnsResult.queryName must not have a trailing root dot")
    query_type = value.get("queryType")
    if not isinstance(query_type, int) or isinstance(query_type, bool) or query_type < 1:
        fail("dnsResult.queryType must be a positive IANA QTYPE")
    response_code = value.get("responseCode")
    if not isinstance(response_code, int) or isinstance(response_code, bool) or not 0 <= response_code <= 65535:
        fail("dnsResult.responseCode must be an integer from 0 through 65535")
    if value.get("transport") in (None, 0, "DNS_TRANSPORT_UNSPECIFIED"):
        fail("dnsResult.transport must be specified")
    if "resolver" in value:
        validate_endpoint(value["resolver"], "dnsResult.resolver")
    validate_duration(value.get("elapsed"), "dnsResult.elapsed")


def validate_http(value: Any) -> None:
    if not isinstance(value, dict):
        fail("httpResult must be an object")
    method = nonempty_string(value.get("method"), "httpResult.method")
    if method != method.upper():
        fail("httpResult.method must be uppercase")
    validate_absolute_url(value.get("finalUrl"), "httpResult.finalUrl", ("http", "https"))
    status_code = value.get("statusCode")
    if not isinstance(status_code, int) or isinstance(status_code, bool) or not 100 <= status_code <= 599:
        fail("httpResult.statusCode must be an integer from 100 through 599")
    validate_duration(value.get("elapsed"), "httpResult.elapsed")


def validate_tcp(value: Any) -> None:
    if not isinstance(value, dict):
        fail("tcpConnectResult must be an object")
    validate_endpoint(value.get("remoteEndpoint"), "tcpConnectResult.remoteEndpoint")
    if "localEndpoint" in value:
        validate_endpoint(value["localEndpoint"], "tcpConnectResult.localEndpoint")
    validate_duration(value.get("elapsed"), "tcpConnectResult.elapsed")


def validate_tls(value: Any) -> None:
    if not isinstance(value, dict):
        fail("tlsHandshakeResult must be an object")
    validate_endpoint(value.get("remoteEndpoint"), "tlsHandshakeResult.remoteEndpoint")
    nonempty_string(value.get("protocolVersion"), "tlsHandshakeResult.protocolVersion")
    nonempty_string(value.get("cipherSuite"), "tlsHandshakeResult.cipherSuite")
    validate_duration(value.get("elapsed"), "tlsHandshakeResult.elapsed")


RESULT_VALIDATORS = {
    "dnsResult": validate_dns,
    "httpResult": validate_http,
    "tcpConnectResult": validate_tcp,
    "tlsHandshakeResult": validate_tls,
}


def validate_measurement(value: Any) -> None:
    if not isinstance(value, dict):
        fail("measurement must be an object")
    nonempty_string(value.get("measurementId"), "measurementId")
    kind = value.get("kind")
    expected_result = RESULT_FOR_KIND.get(kind)
    if expected_result is None:
        fail("kind must identify a supported Measurement v1 result")

    started = parse_timestamp(value.get("startedAt"), "startedAt")
    finished = parse_timestamp(value.get("finishedAt"), "finishedAt")
    if finished < started:
        fail("finishedAt must not precede startedAt")

    validate_probe(value.get("probe"))
    if "network" in value:
        validate_network(value["network"])
    validate_target(value.get("target"))

    errors = value.get("errors", [])
    if not isinstance(errors, list):
        fail("errors must be a list")
    for index, error in enumerate(errors):
        validate_error(error, index)

    present_results = [field for field in RESULT_FIELDS if field in value]
    if len(present_results) > 1:
        fail("at most one result may be present")
    result = present_results[0] if present_results else None
    status = value.get("status")
    if status == "EXECUTION_STATUS_SUCCEEDED":
        if result is None or errors:
            fail("a succeeded measurement requires one result and no errors")
    elif status == "EXECUTION_STATUS_FAILED":
        if result is not None or not errors:
            fail("a failed measurement requires errors and no result")
    elif status == "EXECUTION_STATUS_PARTIAL":
        if result is None or not errors:
            fail("a partial measurement requires one result and errors")
    else:
        fail("status must be a terminal execution status")

    if result is not None:
        if result != expected_result:
            fail(f"{kind} requires {expected_result}")
        RESULT_VALIDATORS[result](value[result])


def reject_duplicate_keys(pairs: Iterable[Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConformanceError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fixture:
        return json.load(fixture, object_pairs_hook=reject_duplicate_keys)


def run_buf(buf: str, source: Path, destination: Path, source_format: str, destination_format: str) -> None:
    command = [
        buf,
        "convert",
        str(ROOT),
        "--type",
        MESSAGE_TYPE,
        "--from",
        f"{source}#format={source_format}",
        "--to",
        f"{destination}#format={destination_format}",
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)


def wire_round_trip(buf: str, fixture: Path) -> Any:
    with tempfile.TemporaryDirectory(prefix="gio-protocol-") as directory:
        temporary = Path(directory)
        first_wire = temporary / "first.binpb"
        first_json = temporary / "first.json"
        second_wire = temporary / "second.binpb"
        second_json = temporary / "second.json"
        run_buf(buf, fixture, first_wire, "json", "binpb")
        run_buf(buf, first_wire, first_json, "binpb", "json")
        run_buf(buf, first_json, second_wire, "json", "binpb")
        run_buf(buf, second_wire, second_json, "binpb", "json")
        decoded = load_json(first_json)
        if decoded != load_json(second_json):
            fail(f"{fixture.name} changed meaning after a wire round trip")
        return decoded


def fixture_paths(category: str) -> List[Path]:
    paths = sorted((FIXTURES / category).glob("*.json"))
    if not paths:
        fail(f"no {category} fixtures found")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--buf", default=os.environ.get("BUF", "buf"))
    arguments = parser.parse_args()

    valid = fixture_paths("valid")
    invalid = fixture_paths("invalid")
    for fixture in valid:
        validate_measurement(wire_round_trip(arguments.buf, fixture))

    for fixture in invalid:
        try:
            validate_measurement(wire_round_trip(arguments.buf, fixture))
        except ConformanceError:
            continue
        fail(f"invalid fixture unexpectedly passed: {fixture.name}")

    print(f"Conformance fixtures passed: {len(valid)} valid, {len(invalid)} invalid")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConformanceError, subprocess.CalledProcessError) as error:
        print(f"conformance error: {error}", file=os.sys.stderr)
        raise SystemExit(1)
