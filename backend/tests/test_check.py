import httpx

from routes import monitors


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeClient:
    def __init__(self, head_results, get_result=None):
        self.head_results = iter(head_results)
        self.get_result = get_result
        self.head_urls = []
        self.get_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def head(self, url):
        self.head_urls.append(url)
        result = next(self.head_results)
        if isinstance(result, Exception):
            raise result
        return result

    def get(self, url, headers):
        self.get_calls.append((url, headers))
        if isinstance(self.get_result, Exception):
            raise self.get_result
        return self.get_result


def prepare_public_target(monkeypatch):
    monkeypatch.setattr(
        monitors,
        "get_public_addresses",
        lambda target: ["93.184.216.34"],
    )
    monkeypatch.setattr(
        monitors,
        "utc_timestamp",
        lambda: "2026-07-31T12:00:00Z",
    )


def test_check_target_returns_down_when_dns_lookup_fails(monkeypatch):
    monkeypatch.setattr(monitors, "get_public_addresses", lambda target: [])

    def fail_if_http_client_is_created(**kwargs):
        raise AssertionError("HTTP client should not be created after DNS failure")

    monkeypatch.setattr(monitors.httpx, "Client", fail_if_http_client_is_created)

    result = monitors.check_target("example.com", timeout=5)

    assert result["target"] == "example.com"
    assert result["status"] == "down"
    assert result["latency"] is None
    assert result["status_code"] is None
    assert result["error"] == "DNS lookup failed."


def test_check_target_returns_up_for_successful_head_request(monkeypatch):
    prepare_public_target(monkeypatch)
    fake_client = FakeClient([FakeResponse(204)])
    timer = iter([10.0, 10.0424])
    monkeypatch.setattr(monitors.time, "perf_counter", timer.__next__)
    monkeypatch.setattr(monitors.httpx, "Client", lambda **kwargs: fake_client)

    result = monitors.check_target("example.com", timeout=5)

    assert result == {
        "target": "example.com",
        "status": "up",
        "latency": 42.4,
        "status_code": 204,
        "checked_at": "2026-07-31T12:00:00Z",
        "error": None,
    }
    assert fake_client.head_urls == ["https://example.com"]


def test_check_target_marks_server_errors_as_issues(monkeypatch):
    prepare_public_target(monkeypatch)
    fake_client = FakeClient([FakeResponse(503)])
    timer = iter([20.0, 20.01])
    monkeypatch.setattr(monitors.time, "perf_counter", timer.__next__)
    monkeypatch.setattr(monitors.httpx, "Client", lambda **kwargs: fake_client)

    result = monitors.check_target("http://example.com", timeout=5)

    assert result["status"] == "issues"
    assert result["status_code"] == 503
    assert result["latency"] == 10.0
    assert fake_client.head_urls == ["http://example.com"]


def test_check_target_uses_ranged_get_when_head_is_not_allowed(monkeypatch):
    prepare_public_target(monkeypatch)
    fake_client = FakeClient([FakeResponse(405)], get_result=FakeResponse(206))
    timer = iter([30.0, 30.025])
    monkeypatch.setattr(monitors.time, "perf_counter", timer.__next__)
    monkeypatch.setattr(monitors.httpx, "Client", lambda **kwargs: fake_client)

    result = monitors.check_target("example.com", timeout=5)

    assert result["status"] == "up"
    assert result["status_code"] == 206
    assert fake_client.get_calls == [("https://example.com", {"Range": "bytes=0-0"})]


def test_check_target_falls_back_from_https_to_http(monkeypatch):
    prepare_public_target(monkeypatch)
    fake_client = FakeClient(
        [
            httpx.TimeoutException("HTTPS timed out"),
            FakeResponse(200),
        ]
    )
    timer = iter([40.0, 41.0, 41.03])
    monkeypatch.setattr(monitors.time, "perf_counter", timer.__next__)
    monkeypatch.setattr(monitors.httpx, "Client", lambda **kwargs: fake_client)

    result = monitors.check_target("example.com", timeout=5)

    assert result["status"] == "up"
    assert result["status_code"] == 200
    assert fake_client.head_urls == [
        "https://example.com",
        "http://example.com",
    ]


def test_check_target_returns_down_after_both_schemes_time_out(monkeypatch):
    prepare_public_target(monkeypatch)
    fake_client = FakeClient(
        [
            httpx.TimeoutException("HTTPS timed out"),
            httpx.TimeoutException("HTTP timed out"),
        ]
    )
    timer = iter([50.0, 51.0])
    monkeypatch.setattr(monitors.time, "perf_counter", timer.__next__)
    monkeypatch.setattr(monitors.httpx, "Client", lambda **kwargs: fake_client)

    result = monitors.check_target("example.com", timeout=5)

    assert result["status"] == "down"
    assert result["status_code"] is None
    assert result["latency"] is None
    assert result["error"] == "The connection timed out."
    assert fake_client.head_urls == [
        "https://example.com",
        "http://example.com",
    ]