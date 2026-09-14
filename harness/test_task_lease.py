"""Reference-model conformance for Task Assignment / Lease v1."""

from copy import deepcopy
import base64
from datetime import datetime
import json
import re
from urllib.parse import urlsplit


STORED = "INGESTION_STATUS_STORED"
ALREADY_STORED = "INGESTION_STATUS_ALREADY_STORED"
RETRY = "INGESTION_STATUS_RETRY"
REJECTED = "INGESTION_STATUS_REJECTED"
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _nonempty(value, field):
    _require(isinstance(value, str) and bool(value), f"{field} must be non-empty")


def _endpoint(value, field):
    _require(isinstance(value, dict), f"{field} must be present")
    address = (value.get("ipAddress") or {}).get("address")
    _require(isinstance(address, str) and address, f"{field}.ipAddress is required")
    try:
        address_bytes = base64.b64decode(address, validate=True)
    except ValueError as error:
        raise ValueError(f"{field}.ipAddress is not valid bytes") from error
    _require(len(address_bytes) in (4, 16), f"{field}.ipAddress length is invalid")
    _require(value.get("port", 0) in range(1, 65536), f"{field}.port is invalid")


def _task(task):
    _require(isinstance(task, dict), "task must be present")
    kinds = [name for name in ("dns", "http", "tcp", "tls") if name in task]
    _require(len(kinds) == 1, "exactly one task kind is required")
    kind = kinds[0]
    value = task[kind]
    if kind == "dns":
        _nonempty(value.get("queryName"), "dns.queryName")
        _require(not value["queryName"].endswith("."), "dns.queryName must not trail dot")
        _require(value.get("queryType", 0) in (1, 28), "dns.queryType must be A or AAAA")
        if "transport" in value:
            _require(value["transport"] == "DNS_TRANSPORT_UDP", "dns.transport must be UDP")
        if "resolver" in value:
            _endpoint(value["resolver"], "dns.resolver")
    elif kind == "http":
        url = value.get("url")
        _nonempty(url, "http.url")
        try:
            parsed = urlsplit(url)
            port = parsed.port
            valid = (parsed.scheme.lower() in {"http", "https"} and parsed.netloc
                     and parsed.hostname and (port is None or port > 0)
                     and not any(char.isspace() for char in url)
                     and not parsed.netloc.endswith(":")
                     and "@" not in parsed.netloc)
        except ValueError:
            valid = False
        _require(valid, "http.url must be an absolute credential-free HTTP(S) URL")
    elif kind == "tcp":
        _endpoint(value.get("remoteEndpoint"), "tcp.remoteEndpoint")
    else:
        _endpoint(value.get("remoteEndpoint"), "tls.remoteEndpoint")
        if "serverName" in value:
            _nonempty(value["serverName"], "tls.serverName")


def _lease(value):
    _require(isinstance(value, dict), "lease must be present")
    _nonempty(value.get("taskId"), "lease.taskId")
    _nonempty(value.get("leaseId"), "lease.leaseId")
    _require(isinstance(value.get("attempt"), int) and not isinstance(value["attempt"], bool)
             and value["attempt"] >= 1, "lease.attempt must be at least one")
    expires = value.get("expiresAt")
    _nonempty(expires, "lease.expiresAt")
    _require(TIMESTAMP.fullmatch(expires) is not None, "lease.expiresAt must be normalized UTC")
    try:
        datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("lease.expiresAt must be a valid timestamp") from error
    _task(value.get("task"))


def validate_acquire_response(response):
    _require(isinstance(response, dict), "acquire response must be an object")
    outcomes = [name for name in ("lease", "noTask") if name in response]
    _require(len(outcomes) == 1, "acquire response must contain exactly one outcome")
    if outcomes[0] == "lease":
        _lease(response["lease"])
    else:
        _require(response["noTask"] == {}, "noTask must be empty")
    return response


def validate_completion(request):
    _require(isinstance(request, dict), "completion request must be an object")
    _nonempty(request.get("taskId"), "completion.taskId")
    _nonempty(request.get("leaseId"), "completion.leaseId")
    _require(isinstance(request.get("attempt"), int) and not isinstance(request["attempt"], bool)
             and request["attempt"] >= 1, "completion.attempt must be at least one")
    _nonempty(request.get("measurementId"), "completion.measurementId")


def validate_completion_response(response, request):
    _require(isinstance(response, dict), "completion response must be an object")
    for field in ("taskId", "leaseId", "attempt", "measurementId"):
        _require(response.get(field) == request[field], f"completion response {field} mismatch")
    return response


def validate_measurement_for_task(task, measurement):
    """Validate the Task Lease producer mapping without duplicating Measurement validation."""
    _task(task)
    _require(isinstance(measurement, dict), "measurement must be an object")
    _nonempty(measurement.get("measurementId"), "measurement.measurementId")
    kind, spec = next(iter(task.items()))
    expected_kind = {
        "dns": "MEASUREMENT_KIND_DNS",
        "http": "MEASUREMENT_KIND_HTTP",
        "tcp": "MEASUREMENT_KIND_TCP_CONNECT",
        "tls": "MEASUREMENT_KIND_TLS_HANDSHAKE",
    }[kind]
    _require(measurement.get("kind") == expected_kind, "measurement.kind does not match task")
    target = measurement.get("target")
    _require(isinstance(target, dict), "measurement.target is required")
    if kind == "dns":
        _require(target.get("hostname") == spec["queryName"], "DNS target hostname does not match task")
        result = measurement.get("dnsResult")
        if result is not None:
            _require(result.get("queryName") == spec["queryName"], "DNS result query name does not match task")
            _require(result.get("queryType") == spec["queryType"], "DNS result QTYPE does not match task")
            _require(result.get("transport", "DNS_TRANSPORT_UDP") == "DNS_TRANSPORT_UDP",
                     "DNS result transport must be UDP")
            if "resolver" in spec:
                _require(result.get("resolver") == spec["resolver"], "DNS result resolver does not match task")
    elif kind == "http":
        _require(target.get("url") == spec["url"], "HTTP target URL does not match task")
        result = measurement.get("httpResult")
        if result is not None:
            _require(result.get("method") == "GET", "HTTP result method must be GET")
            _require(result.get("finalUrl") == spec["url"], "HTTP result URL does not match task")
    elif kind == "tcp":
        endpoint = spec["remoteEndpoint"]
        _require(target.get("ipAddress") == endpoint.get("ipAddress")
                 and target.get("port") == endpoint.get("port"),
                 "TCP target endpoint does not match task")
        result = measurement.get("tcpConnectResult")
        if result is not None:
            _require(result.get("remoteEndpoint") == endpoint, "TCP result endpoint does not match task")
    else:
        endpoint = spec["remoteEndpoint"]
        _require(target.get("ipAddress") == endpoint.get("ipAddress")
                 and target.get("port") == endpoint.get("port"),
                 "TLS target endpoint does not match task")
        if "serverName" in spec:
            _require(target.get("hostname") == spec["serverName"], "TLS target server name does not match task")
        result = measurement.get("tlsHandshakeResult")
        if result is not None:
            _require(result.get("remoteEndpoint") == endpoint, "TLS result endpoint does not match task")
            if "serverName" in spec:
                _require(result.get("serverName") == spec["serverName"],
                         "TLS result server name does not match task")
    if measurement.get("status") == "EXECUTION_STATUS_FAILED":
        _require(not any(field in measurement for field in
                         ("dnsResult", "httpResult", "tcpConnectResult", "tlsHandshakeResult")),
                 "FAILED measurement must not contain a typed result")
    return measurement


def completion_allowed(ingestion_status):
    return ingestion_status in {STORED, ALREADY_STORED}


def classify_client_outcome(status, response_valid=False, content_type="application/x-protobuf"):
    """Complete only a valid correlated 200; all other outcomes are closed-world."""
    if status == 200 and response_valid and content_type == "application/x-protobuf":
        return "complete"
    if isinstance(status, int) and (200 <= status <= 299 or status == 429
                                    or 500 <= status <= 599):
        return "retry_exact"
    return "operator_intervention"


class ExecutionIdentity:
    """Probe-side durable lease-to-measurement binding model."""

    def __init__(self):
        self.bindings = {}
        self.next_measurement = 1

    def bind(self, lease_id):
        if lease_id not in self.bindings:
            self.bindings[lease_id] = f"measurement-{self.next_measurement:04d}"
            self.next_measurement += 1
        return self.bindings[lease_id]


class TaskLeaseModel:
    """Durable semantic state model; no HTTP server or database."""

    def __init__(self):
        self.tasks = {}
        self.task_attempts = {}
        self.leases = {}
        self.active_by_probe = {}
        self.active_by_task = {}
        self.completed_tasks = set()
        self.next_lease = 1
        self.now_expired = set()

    def add_task(self, task_id, task):
        _task(task)
        self.tasks[task_id] = deepcopy(task)
        self.task_attempts.setdefault(task_id, 0)

    def acquire(self, probe_id, *, authenticated=True, malformed=False):
        # Authentication precedes body parsing and scheduling state lookup.
        if not authenticated:
            return 401, None
        if malformed:
            return 400, None
        active_id = self.active_by_probe.get(probe_id)
        if active_id is not None:
            return 200, {"lease": deepcopy(self.leases[active_id]["wire"])}
        for task_id, task in self.tasks.items():
            if task_id in self.completed_tasks:
                continue
            if task_id in self.active_by_task:
                continue
            attempt = self.task_attempts[task_id] + 1
            lease_id = f"lease-{self.next_lease:04d}"
            self.next_lease += 1
            self.task_attempts[task_id] = attempt
            wire = {"taskId": task_id, "leaseId": lease_id, "attempt": attempt,
                    "expiresAt": "2030-01-01T00:00:00Z", "task": deepcopy(task)}
            # Durable assignment precedes the success response.
            self.leases[lease_id] = {"probe_id": probe_id, "task_id": task_id,
                                     "attempt": attempt, "wire": wire,
                                     "state": "active", "measurement_id": None}
            self.active_by_probe[probe_id] = lease_id
            self.active_by_task[task_id] = lease_id
            return 200, {"lease": deepcopy(wire)}
        return 200, {"noTask": {}}

    def expire(self, lease_id):
        lease = self.leases[lease_id]
        if lease["state"] == "active":
            lease["state"] = "expired"
            self.active_by_probe.pop(lease["probe_id"], None)
            self.active_by_task.pop(lease["task_id"], None)
            self.now_expired.add(lease_id)

    def complete(self, probe_id, request, *, authenticated=True, malformed=False):
        if not authenticated:
            return 401, None
        if malformed:
            return 400, None
        try:
            validate_completion(request)
        except ValueError:
            return 400, None
        lease = self.leases.get(request["leaseId"])
        if lease is None or lease["probe_id"] != probe_id:
            return 404, None
        if request["taskId"] != lease["task_id"] or request["attempt"] != lease["attempt"]:
            return 409, None
        if lease["state"] == "expired":
            return 409, None
        if lease["state"] == "finalized":
            if request["measurementId"] != lease["measurement_id"]:
                return 409, None
            response = {"taskId": lease["task_id"], "leaseId": request["leaseId"],
                        "attempt": lease["attempt"], "measurementId": lease["measurement_id"]}
            return 200, response
        lease["state"] = "finalized"
        lease["measurement_id"] = request["measurementId"]
        self.completed_tasks.add(lease["task_id"])
        self.active_by_probe.pop(probe_id, None)
        self.active_by_task.pop(lease["task_id"], None)
        response = {"taskId": lease["task_id"], "leaseId": request["leaseId"],
                    "attempt": lease["attempt"], "measurementId": request["measurementId"]}
        return 200, response


def run_task_lease_tests(acquire_request_codec, acquire_response_codec,
                         complete_request_codec, complete_response_codec):
    endpoint = {"ipAddress": {"address": "AQIDBA=="}, "port": 443}
    tasks = {
        "task-dns": {"dns": {"queryName": "example.com", "queryType": 1,
                               "transport": "DNS_TRANSPORT_UDP", "resolver": endpoint}},
        "task-http": {"http": {"url": "https://example.com/"}},
        "task-tcp": {"tcp": {"remoteEndpoint": endpoint}},
        "task-tls": {"tls": {"remoteEndpoint": endpoint, "serverName": "example.com"}},
    }
    model = TaskLeaseModel()
    for task_id, task in tasks.items():
        model.add_task(task_id, task)
    identity = ExecutionIdentity()
    acquire_cases = completion_cases = mapping_cases = 0

    def expect_invalid(task):
        try:
            _task(task)
        except (ValueError, AttributeError):
            return
        raise AssertionError("invalid task was accepted")

    # Task dispatch is deliberately narrower than the full Measurement DNS vocabulary.
    _task({"dns": {"queryName": "example.com", "queryType": 1}})
    _task({"dns": {"queryName": "example.com", "queryType": 28,
                    "transport": "DNS_TRANSPORT_UDP"}})
    for query_type in (0, 15, 16, 65535):
        expect_invalid({"dns": {"queryName": "example.com", "queryType": query_type}})
    for transport in ("DNS_TRANSPORT_TCP", "DNS_TRANSPORT_TLS", "DNS_TRANSPORT_HTTPS"):
        expect_invalid({"dns": {"queryName": "example.com", "queryType": 1, "transport": transport}})
    _task({"dns": {"queryName": "example.com", "queryType": 1, "resolver": endpoint}})
    expect_invalid({"dns": {"queryName": "example.com", "queryType": 1,
                              "resolver": {"ipAddress": {"address": "AQI="}, "port": 53}}})
    acquire_cases += 2 + 4 + 3 + 2

    # HTTP task syntax follows the probe's absolute, credential-free URL profile.
    _task({"http": {"url": "https://example.com/"}})
    for url in ("https://user@example.com/", "https://user:password@example.com/",
                "https://@example.com/",
                "https://example.com:0/", "https://example.com:65536/",
                "https://example.com:not-a-port/", "https://example.com:/"):
        expect_invalid({"http": {"url": url}})
    acquire_cases += 1 + 7

    def acquire(probe, **kwargs):
        acquire_request_codec.round_trip({})
        status, response = model.acquire(probe, **kwargs)
        if response is not None:
            response = acquire_response_codec.round_trip(response)
        return status, response

    def complete(probe, request, **kwargs):
        request = complete_request_codec.round_trip(request)
        status, response = model.complete(probe, request, **kwargs)
        if response is not None:
            response = complete_response_codec.round_trip(response)
        return status, response

    empty_model = TaskLeaseModel()
    status, no_task = empty_model.acquire("probe-empty")
    no_task = acquire_response_codec.round_trip(no_task)
    assert status == 200 and "noTask" in no_task
    validate_acquire_response(no_task)
    acquire_cases += 1

    status_expectations = {
        200: "complete", 201: "retry_exact", 202: "retry_exact", 204: "retry_exact",
        301: "operator_intervention", 302: "operator_intervention", 303: "operator_intervention",
        307: "operator_intervention", 308: "operator_intervention",
        400: "operator_intervention", 401: "operator_intervention", 403: "operator_intervention",
        404: "operator_intervention", 408: "operator_intervention", 409: "operator_intervention",
        422: "operator_intervention", 429: "retry_exact", 500: "retry_exact",
        503: "retry_exact", 599: "retry_exact", 600: "operator_intervention",
    }
    for status, expected in status_expectations.items():
        assert classify_client_outcome(status, response_valid=(status == 200)) == expected
        assert classify_client_outcome(status, response_valid=True) != "complete" or status == 200
        acquire_cases += 1
    assert classify_client_outcome("unknown") == "operator_intervention"
    assert classify_client_outcome(200, response_valid=False) == "retry_exact"
    assert classify_client_outcome(200, response_valid=True, content_type="text/plain") == "retry_exact"
    assert classify_client_outcome(200, response_valid=False, content_type="application/x-protobuf") == "retry_exact"
    acquire_cases += 2

    # Normative Task -> Measurement producer mapping. This is intentionally a
    # focused mapping check; full Measurement semantics remain in test_conformance.
    mapping_measurements = {
        "dns": {"measurementId": "m-dns", "kind": "MEASUREMENT_KIND_DNS",
                "target": {"hostname": "example.com"},
                "dnsResult": {"queryName": "example.com", "queryType": 1,
                               "transport": "DNS_TRANSPORT_UDP", "resolver": endpoint}},
        "http": {"measurementId": "m-http", "kind": "MEASUREMENT_KIND_HTTP",
                  "target": {"url": "https://example.com/"},
                  "httpResult": {"method": "GET", "finalUrl": "https://example.com/"}},
        "tcp": {"measurementId": "m-tcp", "kind": "MEASUREMENT_KIND_TCP_CONNECT",
                "target": {"ipAddress": endpoint["ipAddress"], "port": 443},
                "tcpConnectResult": {"remoteEndpoint": endpoint}},
        "tls": {"measurementId": "m-tls", "kind": "MEASUREMENT_KIND_TLS_HANDSHAKE",
                "target": {"hostname": "example.com", "ipAddress": endpoint["ipAddress"], "port": 443},
                "tlsHandshakeResult": {"remoteEndpoint": endpoint, "serverName": "example.com"}},
    }
    for task_id, task in tasks.items():
        kind = next(iter(task))
        validate_measurement_for_task(task, mapping_measurements[kind])
        mapping_cases += 1
    failed_targets = {
        "dns": {"hostname": "example.com"},
        "http": {"url": "https://example.com/"},
        "tcp": {"ipAddress": endpoint["ipAddress"], "port": 443},
        "tls": {"hostname": "example.com", "ipAddress": endpoint["ipAddress"], "port": 443},
    }
    for task in tasks.values():
        kind = next(iter(task))
        failed = {"measurementId": f"m-failed-{kind}",
                  "kind": mapping_measurements[kind]["kind"],
                  "target": failed_targets[kind], "status": "EXECUTION_STATUS_FAILED"}
        validate_measurement_for_task(task, failed)
        mapping_cases += 1
    for bad in (
        (tasks["task-dns"], dict(mapping_measurements["dns"], target={"hostname": "other.example"})),
        (tasks["task-dns"], dict(mapping_measurements["dns"], dnsResult={"queryName": "other.example", "queryType": 1, "transport": "DNS_TRANSPORT_UDP", "resolver": endpoint})),
        (tasks["task-dns"], dict(mapping_measurements["dns"], dnsResult={"queryName": "example.com", "queryType": 28, "transport": "DNS_TRANSPORT_UDP", "resolver": endpoint})),
        (tasks["task-dns"], dict(mapping_measurements["http"], kind="MEASUREMENT_KIND_HTTP")),
        (tasks["task-http"], dict(mapping_measurements["http"], httpResult={"method": "POST", "finalUrl": "https://example.com/"})),
        (tasks["task-tcp"], dict(mapping_measurements["tcp"], target={"ipAddress": endpoint["ipAddress"], "port": 444})),
        (tasks["task-tls"], dict(mapping_measurements["tls"], tlsHandshakeResult={"remoteEndpoint": endpoint, "serverName": "other.example"})),
    ):
        try:
            validate_measurement_for_task(*bad)
        except ValueError:
            mapping_cases += 1
        else:
            raise AssertionError("invalid task-to-measurement mapping was accepted")

    status, first = acquire("probe-a")
    assert status == 200 and "lease" in first
    validate_acquire_response(first)
    lease = first["lease"]
    acquire_cases += 1
    single_task = TaskLeaseModel()
    single_task.add_task("only-task", tasks["task-http"])
    status, _ = single_task.acquire("probe-one")
    assert status == 200
    status, no_second_lease = single_task.acquire("probe-two")
    assert status == 200 and "noTask" in no_second_lease
    acquire_cases += 1
    before = deepcopy(model.leases)
    status, retry = acquire("probe-a")
    assert status == 200 and retry == first and model.leases == before
    acquire_cases += 1
    status, response_lost_retry = acquire("probe-a")
    assert response_lost_retry == first and status == 200
    acquire_cases += 1

    # Invalid credentials cannot disclose malformed input, active lease, or available work.
    for kwargs in ({"authenticated": False, "malformed": True}, {"authenticated": False}):
        status, response = acquire("probe-a", **kwargs)
        assert status == 401 and response is None
        acquire_cases += 1
    status, response = acquire("probe-new", malformed=True)
    assert status == 400 and response is None
    acquire_cases += 1

    # One active lease per probe and one active lease per task.
    status, second_probe = acquire("probe-b")
    assert status == 200 and second_probe["lease"]["taskId"] != lease["taskId"]
    acquire_cases += 1
    status, same_probe = acquire("probe-b")
    assert same_probe == second_probe and status == 200
    acquire_cases += 1

    # Bind the first lease before execution and reuse the ID after reacquisition.
    measurement_id = identity.bind(lease["leaseId"])
    assert identity.bind(lease["leaseId"]) == measurement_id
    acquire_cases += 1

    # Complete the first lease only after a successful ingestion ACK.
    for ingestion_status in (RETRY, REJECTED, None):
        assert not completion_allowed(ingestion_status)
        completion_cases += 1
    assert completion_allowed(STORED) and completion_allowed(ALREADY_STORED)
    completion_cases += 1
    completion_request = {"taskId": lease["taskId"], "leaseId": lease["leaseId"],
                          "attempt": lease["attempt"], "measurementId": measurement_id}
    status, completed = complete("probe-a", completion_request)
    assert status == 200 and completed["measurementId"] == measurement_id
    validate_completion_response(completed, completion_request)
    assert model.leases[lease["leaseId"]]["state"] == "finalized"
    completion_cases += 1
    # A completion is complete only with the canonical media type and exact echo.
    assert classify_client_outcome(200, response_valid=True,
                                   content_type="application/x-protobuf") == "complete"
    for content_type in ("text/plain", "application/json", ""):
        assert classify_client_outcome(200, response_valid=True,
                                       content_type=content_type) == "retry_exact"
        completion_cases += 1
    for _ in ("task", "lease", "attempt", "measurement"):
        assert classify_client_outcome(200, response_valid=False) == "retry_exact"
        completion_cases += 1
    # Durable finalization precedes response; exact retry is idempotent.
    status, exact = complete("probe-a", {"taskId": lease["taskId"], "leaseId": lease["leaseId"],
                                          "attempt": lease["attempt"], "measurementId": measurement_id})
    assert status == 200 and exact == completed
    completion_cases += 1
    status, _ = complete("probe-a", {"taskId": lease["taskId"], "leaseId": lease["leaseId"],
                                      "attempt": lease["attempt"], "measurementId": "measurement-other"})
    assert status == 409
    completion_cases += 1

    for candidate in (
        {"taskId": "wrong", "leaseId": lease["leaseId"], "attempt": lease["attempt"], "measurementId": "m"},
        {"taskId": lease["taskId"], "leaseId": lease["leaseId"], "attempt": 99, "measurementId": "m"},
        {"taskId": "", "leaseId": lease["leaseId"], "attempt": lease["attempt"], "measurementId": "m"},
    ):
        status, _ = complete("probe-a", candidate)
        assert status == (400 if not candidate["taskId"] else 409)
        completion_cases += 1

    # Unknown and foreign leases are indistinguishable; invalid auth wins first.
    foreign_request = {"taskId": second_probe["lease"]["taskId"], "leaseId": second_probe["lease"]["leaseId"],
                       "attempt": second_probe["lease"]["attempt"], "measurementId": "foreign"}
    status, _ = complete("probe-a", foreign_request)
    assert status == 404
    completion_cases += 1
    status, _ = complete("probe-a", {"taskId": "x", "leaseId": "missing", "attempt": 1, "measurementId": "m"},
                         authenticated=False, malformed=True)
    assert status == 401
    completion_cases += 1
    status, _ = complete("probe-a", {"taskId": "x", "leaseId": "missing", "attempt": 1, "measurementId": "m"},
                         malformed=True)
    assert status == 400
    completion_cases += 1
    status, _ = complete("probe-a", {"taskId": "x", "leaseId": "missing", "attempt": 1, "measurementId": "m"})
    assert status == 404
    completion_cases += 1

    # Expiry creates a new lease ID and incremented attempt for the same task.
    model.expire(second_probe["lease"]["leaseId"])
    status, reissued = acquire("probe-b")
    assert status == 200 and reissued["lease"]["taskId"] == second_probe["lease"]["taskId"]
    assert reissued["lease"]["leaseId"] != second_probe["lease"]["leaseId"]
    assert reissued["lease"]["attempt"] == second_probe["lease"]["attempt"] + 1
    new_measurement = identity.bind(reissued["lease"]["leaseId"])
    assert new_measurement != identity.bind(second_probe["lease"]["leaseId"])
    acquire_cases += 1
    status, _ = complete("probe-b", {"taskId": second_probe["lease"]["taskId"],
                                      "leaseId": second_probe["lease"]["leaseId"],
                                      "attempt": second_probe["lease"]["attempt"],
                                      "measurementId": "old"})
    assert status == 409
    completion_cases += 1

    # Acquire response oneof and task-shape validation, including malformed outcomes.
    for invalid in ({}, {"lease": lease, "noTask": {}},
                    {"lease": dict(lease, attempt=0)},
                    {"lease": dict(lease, task={"http": {"url": "relative"}})}):
        try:
            validate_acquire_response(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid acquire response was accepted")
        acquire_cases += 1

    # Unknown protobuf fields do not invalidate known task semantics.
    descriptor = json.loads(acquire_response_codec.schema.read_text(encoding="utf-8"))
    file = next(f for f in descriptor["file"] if f["name"] == "gio/control/v1/task.proto")
    message = next(m for m in file["messageType"] if m["name"] == "TaskLease")
    message["field"].append({"name": "future_marker", "jsonName": "futureMarker", "number": 1000,
                              "label": "LABEL_OPTIONAL", "type": "TYPE_STRING"})
    future = acquire_response_codec.directory / "task-lease-future.json"
    future.write_text(json.dumps(descriptor), encoding="utf-8")
    future_value = {"lease": dict(lease, futureMarker="future")}
    decoded = acquire_response_codec.decode(acquire_response_codec.encode(future_value, future))
    validate_acquire_response(decoded)
    acquire_cases += 1

    return acquire_cases, completion_cases, mapping_cases, acquire_cases + completion_cases + mapping_cases
