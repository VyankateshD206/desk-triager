import json
import time

import httpx
import pytest

from triager.config import Settings
from triager.providers import complete, response_input


def test_openai_responses_tool_roundtrip_preserves_call_ids(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    client = httpx.Client
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        if len(requests) == 1:
            output = [
                {
                    "type": "function_call",
                    "name": "get_metrics",
                    "call_id": "call_1",
                    "arguments": "{}",
                }
            ]
        else:
            assert requests[-1]["input"][-1] == {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": '{"result": 650}',
            }
            output = [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": '{"answer":650}'}],
                }
            ]
        return httpx.Response(
            200, json={"output": output, "usage": {"input_tokens": 20, "output_tokens": 10}}
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(handler), **kw)
    )
    settings = Settings(ai_provider="openai")
    contents = [{"role": "user", "parts": [{"text": "Return JSON"}]}]
    first = complete(settings, "Return JSON", contents, [], time.time() + 30)
    assert first["_usage"]["input_tokens"] == 20
    assert first["_provider"] == "openai"
    contents.append({k: v for k, v in first.items() if k not in {"_usage", "_provider"}})
    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "get_metrics",
                        "id": "call_1",
                        "response": {"result": 650},
                    }
                }
            ],
        }
    )
    second = complete(settings, "Return JSON", contents, [], time.time() + 30)
    assert second["parts"][0]["text"] == '{"answer":650}'
    assert requests[0]["store"] is False


def test_gemini_failure_can_use_explicit_openai_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-gemini-key")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-key")
    client = httpx.Client

    def handler(request):
        if "googleapis.com" in request.url.host:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
                "usage": {},
            },
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(handler), **kw)
    )
    result = complete(
        Settings(ai_provider="gemini", fallback_provider="openai"),
        "JSON",
        [{"role": "user", "parts": [{"text": "JSON"}]}],
        [],
        time.time() + 30,
    )
    assert result["_provider"] == "openai"
    assert result["_provider_fallback"] is True


def test_orphaned_tool_outputs_are_rejected():
    with pytest.raises(ValueError):
        response_input(
            [{"role": "user", "parts": [{"functionResponse": {"name": "missing", "response": {}}}]}]
        )
