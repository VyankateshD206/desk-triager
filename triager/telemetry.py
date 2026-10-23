"""Opt-in OpenTelemetry export and dated token-cost estimates."""

import json
import os
from importlib.resources import files


def configure_tracing():
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "desk-triager"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider


def estimate_cost(calls):
    prices = json.loads(files("triager").joinpath("knowledge/pricing.json").read_text())
    total = 0.0
    for call in calls:
        price = prices["models"].get(call.get("model"))
        if (
            not price
            or call.get("input_tokens") is None
            or call.get("output_tokens") is None
            or call.get("prior_failed_attempts")
        ):
            return None
        total += (
            call["input_tokens"] * price["input_per_million"]
            + call["output_tokens"] * price["output_per_million"]
        ) / 1_000_000
    return total
