import httpx
import pytest

from triager.config import Settings
from triager.observability import ObservabilityTools


def configured():
    return Settings(
        loki_url="http://loki:3100",
        prometheus_url="http://prom:9090",
        demo_service_url="http://demo:8001",
    )


def test_queries_are_bounded_and_service_scoped(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs)
    )
    tools = ObservabilityTools(configured()).tools("execution-gateway")
    tools["query_logs"]()
    tools["get_metrics"]()
    tools["list_deployments"]()
    tools["get_deploy_diff"]()
    assert all(r.method == "GET" for r in requests)
    logs = requests[0].url.params
    assert logs["query"] == '{service="execution-gateway"}'
    assert logs["limit"] == "50"
    assert int(logs["end"]) - int(logs["start"]) == 300_000_000_000
    assert 'service="execution-gateway"' in requests[1].url.params["query"]
    assert requests[2].url.params["service"] == "execution-gateway"
    assert requests[3].url.path == "/deployments/latest/diff"


def test_disabled_sources_expose_no_tools():
    settings = Settings(loki_url="", prometheus_url="", demo_service_url="")
    assert ObservabilityTools(settings).tools("market-feed") == {}
    with pytest.raises(ValueError):
        ObservabilityTools(settings).tools('gateway"} or {}')


@pytest.mark.parametrize(
    "status,body", [(302, {}), (503, {}), (200, {"status": "error"}), (200, "x" * 262145)]
)
def test_unavailable_or_oversized_source_is_rejected(monkeypatch, status, body):
    client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)), **kwargs
        ),
    )
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        ObservabilityTools(configured()).tools("market-feed")["query_logs"]()
