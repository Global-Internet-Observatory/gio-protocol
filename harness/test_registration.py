"""Reference-model conformance for Probe Registration & Credential Provisioning v1."""

import base64
from copy import deepcopy
import hashlib
import json
import re


TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class RegistrationError(ValueError):
    """A registration outcome or invariant is invalid."""


class RegistrationModel:
    """Small durable-state model; intentionally no HTTP server or database."""

    def __init__(self):
        self.enrollment = {}
        self.registrations = {}
        self.next_probe = 1

    def add_enrollment(self, token, state="active"):
        self.enrollment[token] = {"state": state, "registration_id": None}

    @staticmethod
    def _verifier(token):
        return hashlib.sha256(token.encode()).digest()

    @staticmethod
    def _valid_token(value):
        if not isinstance(value, str) or TOKEN.fullmatch(value) is None:
            return False
        try:
            raw = base64.urlsafe_b64decode(value + "=")
        except ValueError:
            return False
        return len(raw) == 32 and base64.urlsafe_b64encode(raw).decode().rstrip("=") == value

    @staticmethod
    def _valid_request(request, enrollment_token=None):
        if not isinstance(request, dict):
            return False
        registration_id = request.get("registrationId")
        if not isinstance(registration_id, str) or not registration_id:
            return False
        if len(registration_id.encode("utf-8")) > 128:
            return False
        control = request.get("controlBearerToken")
        ingestion = request.get("ingestionBearerToken")
        return (
            RegistrationModel._valid_token(control)
            and RegistrationModel._valid_token(ingestion)
            and control != ingestion
            and (enrollment_token is None or enrollment_token not in (control, ingestion))
        )

    def register(self, enrollment_token, request, *, malformed=False):
        # Authentication is deliberately first: no request/state oracle.
        identity = self.enrollment.get(enrollment_token)
        if identity is None or identity["state"] in {"expired", "revoked"}:
            return 401, None
        registration_id = request.get("registrationId") if isinstance(request, dict) else None
        bound = identity["registration_id"]
        if identity["state"] == "consumed":
            if bound is None or registration_id != bound:
                return 401, None
            existing = self.registrations[bound]
            if malformed or not self._valid_request(request, enrollment_token):
                return 400, None
            if (self._verifier(request["controlBearerToken"]) == existing["control_verifier"]
                    and self._verifier(request["ingestionBearerToken"]) == existing["ingestion_verifier"]):
                return 200, {"registrationId": bound, "probeId": existing["probe_id"]}
            return 409, None
        if malformed or not self._valid_request(request, enrollment_token):
            return 400, None
        control = request["controlBearerToken"]
        ingestion = request["ingestionBearerToken"]
        existing = self.registrations.get(registration_id)
        if existing is not None:
            return 409, None
        probe_id = f"probe-{self.next_probe:04d}"
        # Commit all logical state together in this model.
        self.registrations[registration_id] = {
            "probe_id": probe_id,
            "control_verifier": self._verifier(control),
            "ingestion_verifier": self._verifier(ingestion),
        }
        identity["state"] = "consumed"
        identity["registration_id"] = registration_id
        self.next_probe += 1
        return 200, {"registrationId": registration_id, "probeId": probe_id}


def classify_client_outcome(status, response_valid=False):
    """Return completion only for a correlated 200 application response."""
    if status == 200 and response_valid:
        return "complete"
    if not isinstance(status, int):
        return "operator_intervention"
    if status == 429 or 500 <= status <= 599 or 200 <= status <= 299:
        return "retry_exact"
    # Every unrecognized non-2xx status is non-completing. 3xx and remaining
    # 4xx fall back to intervention; 5xx is retry_exact above (HTTP.md).
    return "operator_intervention"


def parse_bearer_authorization(headers):
    """Apply the Authentication v1 Bearer header boundary."""
    authorization = [value for name, value in headers if name.lower() == "authorization"]
    if len(authorization) != 1:
        return None
    parts = authorization[0].split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    credential = parts[1]
    if any(char.isspace() for char in credential) or "," in credential:
        return None
    return credential


def _token(byte):
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode().rstrip("=")


def run_registration_tests(request_codec, response_codec):
    model = RegistrationModel()
    enrollment = "enroll-one-time"
    other_enrollment = "enroll-other"
    model.add_enrollment(enrollment)
    model.add_enrollment(other_enrollment)
    model.add_enrollment("enroll-expired", "expired")
    model.add_enrollment("enroll-revoked", "revoked")
    control = _token(1)
    ingestion = _token(2)
    request = {"registrationId": "install-opaque-1", "controlBearerToken": control,
               "ingestionBearerToken": ingestion}
    cases = 0

    def outcome(token, candidate, **kwargs):
        status, response = model.register(token, candidate, **kwargs)
        if response is not None:
            response = response_codec.round_trip(response)
        return status, response

    def valid_response(response, request_value):
        return (isinstance(response, dict)
                and isinstance(response.get("registrationId"), str)
                and response["registrationId"] == request_value["registrationId"]
                and isinstance(response.get("probeId"), str)
                and bool(response["probeId"]))

    status, response = outcome(enrollment, request)
    assert status == 200 and valid_response(response, request)
    assert response["probeId"] == "probe-0001"
    cases += 1
    # Authenticated malformed protobuf is validation failure and leaves no state.
    model.add_enrollment("enroll-malformed")
    before = deepcopy(model.registrations)
    status, _ = outcome("enroll-malformed", {}, malformed=True)
    assert status == 400 and model.registrations == before
    cases += 1
    before = deepcopy(model.registrations)
    status, retry = outcome(enrollment, request)
    assert status == 200 and retry == response and model.registrations == before
    cases += 1
    # Response loss is modeled by discarding the first response and retrying exactly.
    status, recovered = outcome(enrollment, request)
    assert status == 200 and recovered["probeId"] == response["probeId"]
    cases += 1

    for token in ("unknown", "", "enroll-expired", "enroll-revoked"):
        status, _ = outcome(token, {"malformed": True}, malformed=True)
        assert status == 401
        cases += 1
    bearer_cases = (
        ([], None),
        ([("Authorization", "")], None),
        ([("Authorization", "Bearer")], None),
        ([("Authorization", "Bearer token-a"), ("authorization", "Bearer token-a")], None),
        ([("Authorization", "Bearer token-a, Bearer token-b")], None),
        ([("Authorization", "Bearer token-a")], "token-a"),
        ([("Authorization", "bEaReR token-a")], "token-a"),
    )
    for headers, expected in bearer_cases:
        assert parse_bearer_authorization(headers) == expected
        cases += 1
    status, _ = outcome(enrollment, dict(request, registrationId="other-install"))
    assert status == 401
    cases += 1
    status, _ = outcome("unknown", {"registrationId": request["registrationId"]}, malformed=True)
    assert status == 401
    cases += 1

    for candidate in (
        dict(request, registrationId=""),
        dict(request, registrationId="x" * 129),
        dict(request, controlBearerToken=ingestion),
        dict(request, controlBearerToken="bad"),
        dict(request, ingestionBearerToken="bad"),
    ):
        before = deepcopy(model.registrations)
        status, _ = outcome(other_enrollment, candidate)
        assert status == 400 and model.registrations == before
        cases += 1

    # Enrollment/runtime equality is request-invalid on the active path.
    for token, candidate in (
        (_token(9), dict(request, controlBearerToken=_token(9))),
        (_token(10), dict(request, ingestionBearerToken=_token(10))),
    ):
        model.add_enrollment(token)
        before = deepcopy(model.registrations)
        status, _ = outcome(token, candidate)
        assert status == 400 and model.registrations == before
        cases += 1

    for changed in (dict(request, controlBearerToken=_token(3)),
                    dict(request, ingestionBearerToken=_token(4))):
        status, _ = outcome(enrollment, changed)
        assert status == 409
        cases += 1

    # The same equality rule applies after consumption, before conflict handling.
    consumed_enrollment = _token(11)
    consumed_request = {"registrationId": "install-opaque-2", "controlBearerToken": _token(12),
                        "ingestionBearerToken": _token(13)}
    model.add_enrollment(consumed_enrollment)
    status, _ = outcome(consumed_enrollment, consumed_request)
    assert status == 200
    cases += 1
    for candidate in (dict(consumed_request, controlBearerToken=consumed_enrollment),
                      dict(consumed_request, ingestionBearerToken=consumed_enrollment)):
        status, _ = outcome(consumed_enrollment, candidate)
        assert status == 400
        cases += 1

    # A different valid enrollment identity cannot claim an occupied ID.
    model.add_enrollment("enroll-third")
    status, _ = outcome("enroll-third", request)
    assert status == 409 and model.registrations[request["registrationId"]]["probe_id"] == "probe-0001"
    cases += 1

    status_expectations = {
        200: "complete",
        201: "retry_exact",
        202: "retry_exact",
        204: "retry_exact",
        206: "retry_exact",
        301: "operator_intervention",
        302: "operator_intervention",
        303: "operator_intervention",
        307: "operator_intervention",
        308: "operator_intervention",
        400: "operator_intervention",
        401: "operator_intervention",
        403: "operator_intervention",
        404: "operator_intervention",
        405: "operator_intervention",
        408: "operator_intervention",
        409: "operator_intervention",
        410: "operator_intervention",
        418: "operator_intervention",
        422: "operator_intervention",
        451: "operator_intervention",
        429: "retry_exact",
        500: "retry_exact",
        503: "retry_exact",
        599: "retry_exact",
        600: "operator_intervention",
    }
    for status, expected in status_expectations.items():
        response_valid = status == 200
        assert classify_client_outcome(status, response_valid=response_valid) == expected
        cases += 1
    assert classify_client_outcome(200, response_valid=False) == "retry_exact"
    cases += 1
    for status in status_expectations:
        if status != 200:
            for response_valid in (False, True):
                assert classify_client_outcome(status, response_valid) != "complete"
    assert classify_client_outcome(200, response_valid=True) == "complete"
    assert classify_client_outcome("unknown") == "operator_intervention"
    cases += 1

    # The client rejects a response that does not correlate to its request.
    mismatched = {"registrationId": "other-install", "probeId": "probe-0001"}
    decoded_mismatch = response_codec.round_trip(mismatched)
    assert decoded_mismatch["registrationId"] != request["registrationId"]
    assert classify_client_outcome(200, response_valid=False) == "retry_exact"
    cases += 1

    # Known fields remain valid when an unknown future field is present on the wire.
    descriptor = json.loads(request_codec.schema.read_text(encoding="utf-8"))
    file = next(f for f in descriptor["file"] if f["name"] == "gio/control/v1/registration.proto")
    message = next(m for m in file["messageType"] if m["name"] == "RegisterProbeRequest")
    message["field"].append({"name": "future_marker", "jsonName": "futureMarker", "number": 1000,
                              "label": "LABEL_OPTIONAL", "type": "TYPE_STRING"})
    future = request_codec.directory / "registration-future.json"
    future.write_text(json.dumps(descriptor), encoding="utf-8")
    future_bytes = request_codec.encode(dict(request, futureMarker="future"), future)
    decoded = request_codec.decode(future_bytes)
    assert decoded == request
    cases += 1

    return cases
