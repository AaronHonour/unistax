"""Trace exporters configuration."""

from dataclasses import dataclass
from enum import Enum

from opentelemetry.exporter.jaeger.thrift import JaegerExporter  # type: ignore[import-not-found]
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
    OTLPSpanExporter,
)
from opentelemetry.exporter.zipkin.json import ZipkinExporter  # type: ignore[import-not-found]
from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
    ConsoleSpanExporter,
    SpanExporter,
)


class ExporterType(str, Enum):
    """Exporter type enumeration."""

    CONSOLE = "console"
    JAEGER = "jaeger"
    ZIPKIN = "zipkin"
    OTLP = "otlp"


@dataclass
class ExporterConfig:
    """Exporter configuration."""

    type: ExporterType
    endpoint: str | None = None
    service_name: str | None = None
    agent_host: str | None = None
    agent_port: int | None = None
    max_tag_value_length: int | None = None
    insecure: bool = False


def create_exporter(config: ExporterConfig) -> SpanExporter:
    """Create span exporter from configuration.

    Args:
        config: Exporter configuration

    Returns:
        SpanExporter instance

    Raises:
        ValueError: If exporter type is unknown
    """
    if config.type == ExporterType.CONSOLE:
        return ConsoleSpanExporter()

    elif config.type == ExporterType.JAEGER:
        kwargs: dict[str, int | str] = {}
        if config.agent_host:
            kwargs["agent_host_name"] = config.agent_host
        if config.agent_port:
            kwargs["agent_port"] = config.agent_port
        if config.max_tag_value_length:
            kwargs["max_tag_value_length"] = config.max_tag_value_length

        return JaegerExporter(**kwargs)

    elif config.type == ExporterType.ZIPKIN:
        zipkin_kwargs: dict[str, int | str] = {}
        if config.endpoint:
            zipkin_kwargs["endpoint"] = config.endpoint
        if config.max_tag_value_length:
            zipkin_kwargs["max_tag_value_length"] = config.max_tag_value_length

        return ZipkinExporter(**zipkin_kwargs)

    elif config.type == ExporterType.OTLP:
        otlp_kwargs: dict[str, bool | str] = {}
        if config.endpoint:
            otlp_kwargs["endpoint"] = config.endpoint
        if config.insecure:
            otlp_kwargs["insecure"] = config.insecure

        return OTLPSpanExporter(**otlp_kwargs)

    else:
        raise ValueError(f"Unknown exporter type: {config.type}")
