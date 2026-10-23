"""Gemini REST and OpenAI Responses adapters using a common tool-call envelope."""

import json
import os
import re
import time

import httpx


def response_input(contents):
    items, calls = [], {}
    for turn, content in enumerate(contents):
        if content.get("_openai_output"):
            items.extend(content["_openai_output"])
            for part in content.get("parts", []):
                if "functionCall" in part:
                    call = part["functionCall"]
                    calls.setdefault(call["name"], []).append(call["id"])
            continue
        for index, part in enumerate(content.get("parts", [])):
            if "functionCall" in part:
                call = part["functionCall"]
                call_id = call.get("id", f"call_{turn}_{index}")
                calls.setdefault(call["name"], []).append(call_id)
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": call["name"],
                        "arguments": json.dumps(call.get("args", {})),
                    }
                )
            elif "functionResponse" in part:
                result = part["functionResponse"]
                pending = calls.get(result["name"], [])
                call_id = result.get("id") or (pending[0] if pending else None)
                if not call_id:
                    raise ValueError("Orphaned function result")
                if pending:
                    pending.pop(0)
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result["response"]),
                    }
                )
            elif "text" in part and not part.get("thought"):
                items.append(
                    {
                        "role": "assistant" if content["role"] == "model" else "user",
                        "content": part["text"],
                    }
                )
    return items


def request_once(settings, instruction, contents, declarations, timeout, provider):
    model = settings.openai_model if provider == "openai" else settings.gemini_model
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise ValueError("Invalid model identifier")
    started = time.perf_counter()
    with httpx.Client(timeout=timeout) as client:
        if provider == "gemini":
            key = os.getenv("GEMINI_API_KEY", "")
            if not key:
                raise ValueError("GEMINI_API_KEY missing")
            body = {
                "contents": [
                    {k: v for k, v in content.items() if not k.startswith("_")}
                    for content in contents
                ],
                "systemInstruction": {"parts": [{"text": instruction}]},
                "generationConfig": {"maxOutputTokens": 4096},
            }
            if declarations:
                body["tools"] = [{"functionDeclarations": declarations}]
            response = client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                + model
                + ":generateContent",
                headers={"x-goog-api-key": key},
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            result = data["candidates"][0]["content"]
            usage = data.get("usageMetadata", {})
            tokens_in, tokens_out = usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
            if tokens_out is not None:
                tokens_out += usage.get("thoughtsTokenCount", 0)
        elif provider == "openai":
            key = os.getenv("OPENAI_API_KEY", "")
            if not key:
                raise ValueError("OPENAI_API_KEY missing")
            body = {
                "model": model,
                "instructions": instruction,
                "input": response_input(contents),
                "store": False,
                "max_output_tokens": 4096,
                "include": ["reasoning.encrypted_content"],
                "text": {"format": {"type": "json_object"}},
            }
            if declarations:
                body["tools"] = [
                    {
                        "type": "function",
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"],
                        "strict": False,
                    }
                    for tool in declarations
                ]
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": "Bearer " + key},
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            parts = []
            for item in data["output"]:
                if item["type"] == "function_call":
                    parts.append(
                        {
                            "functionCall": {
                                "name": item["name"],
                                "id": item["call_id"],
                                "args": json.loads(item["arguments"]),
                            }
                        }
                    )
                elif item["type"] == "message":
                    parts.extend(
                        {"text": part["text"]}
                        for part in item.get("content", [])
                        if part["type"] == "output_text"
                    )
            result = {"role": "model", "parts": parts, "_openai_output": data["output"]}
            usage = data.get("usage", {})
            tokens_in, tokens_out = usage.get("input_tokens"), usage.get("output_tokens")
        else:
            raise ValueError("Unknown model provider")
    result["_provider"] = provider
    result["_usage"] = {
        "provider": provider,
        "model": model,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "latency_ms": (time.perf_counter() - started) * 1000,
    }
    return result


def complete(settings, instruction, contents, declarations, deadline):
    providers = [settings.ai_provider]
    if settings.fallback_provider not in {"offline", settings.ai_provider}:
        providers.append(settings.fallback_provider)
    failures = 0
    for index, provider in enumerate(providers):
        for attempt in range(2):
            try:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError("Investigation deadline reached")
                result = request_once(
                    settings, instruction, contents, declarations, min(20, remaining), provider
                )
                result["_usage"]["prior_failed_attempts"] = failures
                if index:
                    result["_provider_fallback"] = True
                return result
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                failures += 1
                transient = isinstance(exc, httpx.TransportError) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code in {429, 500, 502, 503, 504}
                )
                if transient and attempt == 0 and deadline - time.time() > 1:
                    time.sleep(0.25)
                    continue
                if index + 1 == len(providers):
                    raise
                break
    raise RuntimeError("No provider configured")
