"""Conformance checks for the Ingestion Authentication v1 HTTP profile.

The verifier and storage below are deliberately tiny fakes.  They exercise the
observable protocol boundary without prescribing a credential database, token
format, or collector implementation.
"""

import base64
from dataclasses import dataclass

from test_ingestion import (
    IngestionError,
    STATUS_ALREADY_STORED,
    STATUS_REJECTED,
    STATUS_STORED,
    digest,
    validate_upload,
)


class AuthenticationFailure(ValueError):
    """A request did not authenticate at the HTTP boundary."""

    status = 401


class AuthorizationFailure(ValueError):
    """An authenticated request claimed a different probe principal."""

    status = 403


@dataclass(frozen=True)
class Credential:
    probe_id: str
    state: str = "active"


class FakeCredentialVerifier:
    """Opaque token map used only by the conformance harness."""

    def __init__(self):
        self.credentials = {
            "token-A": Credential("probe-tokyo-1"),
            "token-B": Credential("probe-osaka-2"),
            "revoked-token": Credential("probe-tokyo-1", "revoked"),
            "expired-token": Credential("probe-tokyo-1", "expired"),
        }

    def verify(self, token):
        credential = self.credentials.get(token)
        if credential is None or credential.state != "active":
            raise AuthenticationFailure("credential was not accepted")
        return credential.probe_id


def parse_authorization(headers):
    """Parse exactly one Bearer credential; never return diagnostics or token text."""
    authorization = [value for name, value in headers if name.lower() == "authorization"]
    if len(authorization) != 1:
        raise AuthenticationFailure("one Authorization header is required")
    parts = authorization[0].split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1] or "," in parts[1]:
        raise AuthenticationFailure("Bearer credential is invalid")
    return parts[1]


def authenticate(headers, verifier):
    return verifier.verify(parse_authorization(headers))


def validate_wrapper(request):
    """Validate request-level fields without interpreting Measurement semantics."""
    if not isinstance(request, dict) or not isinstance(request.get("measurements"), list):
        raise IngestionError("request wrapper is invalid")
    records = request["measurements"]
    if not records:
        raise IngestionError("request wrapper is empty")
    seen = set()
    for upload in records:
        if not isinstance(upload, dict):
            raise IngestionError("measurement upload wrapper is invalid")
        measurement_id = upload.get("measurementId")
        if not isinstance(measurement_id, str) or not measurement_id or measurement_id in seen:
            raise IngestionError("measurement IDs are invalid or duplicated")
        seen.add(measurement_id)
        try:
            payload = base64.b64decode(upload.get("measurementBytes", ""), validate=True)
            supplied_digest = base64.b64decode(upload.get("payloadSha256", ""), validate=True)
        except (TypeError, ValueError) as error:
            raise IngestionError("request wrapper bytes are invalid") from error
        if len(supplied_digest) != 32:
            raise IngestionError("request wrapper digest is invalid")
        if not isinstance(payload, bytes):
            raise IngestionError("request wrapper payload is invalid")


@dataclass
class IngestionResult:
    status: int
    acknowledgements: list | None = None


def evaluate_request(headers, request, request_codec, measurement_codec, verifier, storage):
    """Apply the observable auth/identity/idempotency ordering to a fake store."""
    principal = authenticate(headers, verifier)
    decoded = request_codec.round_trip(request)
    validate_wrapper(decoded)

    # Decode identity before semantic acceptance.  A mixed-identity request is
    # rejected as one request and cannot partially mutate storage.
    identities = []
    for upload in decoded["measurements"]:
        try:
            measurement = measurement_codec.decode(base64.b64decode(upload["measurementBytes"], validate=True))
            identities.append(measurement.get("probe", {}).get("probeId"))
        except (ValueError, KeyError, TypeError):
            # A malformed Measurement has no identity claim to authorize. It
            # remains a per-record validation failure unless another record in
            # the same request makes an explicit unauthorized claim.
            identities.append(None)
    if any(identity is not None and identity != principal for identity in identities):
        raise AuthorizationFailure("measurement probe does not belong to authenticated principal")

    acknowledgements = []
    for upload in decoded["measurements"]:
        measurement_id = upload.get("measurementId", "")
        supplied_digest = base64.b64decode(upload.get("payloadSha256", ""), validate=True)
        try:
            _, payload, supplied_digest = validate_upload(upload, measurement_codec)
        except IngestionError:
            # A correlatable, authenticated record follows normal per-record
            # ingestion semantics; auth failures never become this ACK.
            acknowledgements.append({
                "measurementId": measurement_id,
                "payloadSha256": base64.b64encode(supplied_digest).decode(),
                "status": STATUS_REJECTED,
            })
            continue
        previous = storage.get(measurement_id)
        if previous is None:
            storage[measurement_id] = payload
            status = STATUS_STORED
        elif previous == payload:
            status = STATUS_ALREADY_STORED
        else:
            status = STATUS_REJECTED
        acknowledgements.append({
            "measurementId": measurement_id,
            "payloadSha256": base64.b64encode(supplied_digest).decode(),
            "status": status,
        })
    return IngestionResult(200, acknowledgements)


def _upload(fixture, measurement_codec):
    payload = measurement_codec.encode(fixture)
    return {
        "measurementId": fixture["measurementId"],
        "measurementBytes": base64.b64encode(payload).decode(),
        "payloadSha256": base64.b64encode(digest(payload)).decode(),
    }


def _expect(error_type, operation, status):
    try:
        operation()
    except error_type as error:
        assert error.status == status
        assert not hasattr(error, "acknowledgements")
    else:
        raise AssertionError(f"expected HTTP {status}")


def run_authentication_tests(request_codec, fixtures, measurement_codec):
    import json

    fixture = json.loads((fixtures / "valid" / "successful_dns.json").read_text())
    probe_b = dict(fixture, measurementId="auth-probe-b")
    probe_b["probe"] = dict(fixture["probe"], probeId="probe-osaka-2")
    probe_b_collision = dict(probe_b, measurementId=fixture["measurementId"])
    upload_a = _upload(fixture, measurement_codec)
    upload_b = _upload(probe_b, measurement_codec)
    upload_b_collision = _upload(probe_b_collision, measurement_codec)
    conflicting_a = dict(fixture, probe=dict(fixture["probe"], softwareVersion="0.1.1"))
    conflicting_upload = _upload(conflicting_a, measurement_codec)
    verifier = FakeCredentialVerifier()
    storage = {}
    auth_a = [("Authorization", "Bearer token-A")]
    auth_b = [("authorization", "bearer token-B")]
    cases = 0

    for headers in (
        [],
        [("Authorization", "")],
        [("Authorization", "Bearer")],
        [("Authorization", "Bearer invalid")],
        [("Authorization", "Bearer revoked-token")],
        [("Authorization", "Bearer expired-token")],
        [("Authorization", "Bearer token-A"), ("Authorization", "Bearer token-A")],
        [("Authorization", "Bearer token-A, Bearer token-B")],
    ):
        _expect(AuthenticationFailure, lambda: authenticate(headers, verifier), 401)
        cases += 1

    for scheme in ("Bearer", "bearer", "BEARER"):
        assert authenticate([("Authorization", f"{scheme} token-A")], verifier) == "probe-tokyo-1"
        cases += 1

    _expect(AuthenticationFailure,
            lambda: evaluate_request([], {"measurements": [upload_a]}, request_codec,
                                     measurement_codec, verifier, storage), 401)
    assert storage == {}
    cases += 1

    result = evaluate_request(auth_a, {"measurements": [upload_a]}, request_codec,
                              measurement_codec, verifier, storage)
    assert result.status == 200 and result.acknowledgements[0]["status"] == STATUS_STORED
    cases += 1

    before = dict(storage)
    for request in (
        {"malformed": True},
        {"measurements": [upload_a]},
        {"measurements": [conflicting_upload]},
    ):
        _expect(AuthenticationFailure,
                lambda request=request: evaluate_request(
                    [("Authorization", "Bearer invalid")], request, request_codec,
                    measurement_codec, verifier, storage), 401)
        assert storage == before
        cases += 1

    _expect(AuthorizationFailure,
            lambda: evaluate_request(auth_a, {"measurements": [upload_b]}, request_codec,
                                     measurement_codec, verifier, storage), 403)
    cases += 1

    before = dict(storage)
    _expect(AuthorizationFailure,
            lambda: evaluate_request(auth_a, {"measurements": [upload_a, upload_b]}, request_codec,
                                     measurement_codec, verifier, storage), 403)
    assert storage == before
    cases += 1

    malformed_payload = dict(upload_a, measurementBytes=base64.b64encode(b"not-a-measurement").decode())
    malformed_batch = {"measurements": [malformed_payload, upload_b]}
    _expect(AuthorizationFailure,
            lambda: evaluate_request(auth_a, malformed_batch, request_codec,
                                     measurement_codec, verifier, storage), 403)
    assert storage == before
    cases += 1

    invalid_semantic = dict(fixture, measurementId="auth-invalid", status="EXECUTION_STATUS_FAILED", errors=[])
    invalid_semantic_upload = _upload(invalid_semantic, measurement_codec)
    mixed_invalid_batch = {"measurements": [invalid_semantic_upload, upload_b]}
    _expect(AuthorizationFailure,
            lambda: evaluate_request(auth_a, mixed_invalid_batch, request_codec,
                                     measurement_codec, verifier, storage), 403)
    assert storage == before
    cases += 1

    malformed_only = evaluate_request(auth_a, {"measurements": [malformed_payload]}, request_codec,
                                      measurement_codec, verifier, storage)
    assert malformed_only.acknowledgements[0]["status"] == STATUS_REJECTED
    assert storage == before
    cases += 1

    missing_probe = dict(fixture, measurementId="auth-missing-probe", probe={})
    missing_probe_result = evaluate_request(auth_a, {"measurements": [_upload(missing_probe, measurement_codec)]},
                                             request_codec, measurement_codec, verifier, storage)
    assert missing_probe_result.acknowledgements[0]["status"] == STATUS_REJECTED
    assert storage == before
    cases += 1

    empty_probe_id = dict(fixture, measurementId="auth-empty-probe-id",
                          probe=dict(fixture["probe"], probeId=""))
    empty_probe_result = evaluate_request(auth_a, {"measurements": [_upload(empty_probe_id, measurement_codec)]},
                                          request_codec, measurement_codec, verifier, storage)
    assert empty_probe_result.acknowledgements[0]["status"] == STATUS_REJECTED
    assert storage == before
    cases += 1

    # An already-stored ID belonging to probe A cannot be disclosed to a
    # credential whose payload claims probe A; identity is checked first.
    _expect(AuthorizationFailure,
            lambda: evaluate_request(auth_b, {"measurements": [upload_a]}, request_codec,
                                     measurement_codec, verifier, storage), 403)
    assert storage == before
    cases += 1

    retry = evaluate_request(auth_a, {"measurements": [upload_a]}, request_codec,
                             measurement_codec, verifier, storage)
    assert retry.acknowledgements[0]["status"] == STATUS_ALREADY_STORED
    cases += 1

    collision = evaluate_request(auth_b, {"measurements": [upload_b_collision]}, request_codec,
                                 measurement_codec, verifier, storage)
    assert collision.acknowledgements[0]["status"] == STATUS_REJECTED
    assert storage[fixture["measurementId"]] == measurement_codec.encode(fixture)
    cases += 1

    invalid = dict(fixture, measurementId="auth-invalid-authorized", status="EXECUTION_STATUS_FAILED", errors=[])
    invalid_upload = _upload(invalid, measurement_codec)
    rejected = evaluate_request(auth_a, {"measurements": [invalid_upload]}, request_codec,
                                measurement_codec, verifier, storage)
    assert rejected.acknowledgements[0]["status"] == STATUS_REJECTED
    cases += 1

    return cases
