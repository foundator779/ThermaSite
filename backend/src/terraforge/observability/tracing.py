from __future__ import annotations

from contextlib import nullcontext


def configure_tracing(app, settings) -> None:
    # Local development has no trace exporter, and wrapping FastAPI adds needless
    # compatibility risk to CORS preflight requests. Workflow spans still use the
    # no-op OpenTelemetry provider through ``workflow_span``.
    if not settings.otel_exporter_otlp_endpoint and not settings.cloud_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment": settings.terraforge_env,
            }
        )
    )
    if settings.otel_exporter_otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
        )
    elif settings.cloud_enabled:
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

            provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))
        except ImportError:
            pass
    trace.set_tracer_provider(provider)
    # FastAPI request auto-instrumentation is deliberately omitted. The current
    # OpenTelemetry middleware attempts to inspect FastAPI's internal
    # ``_IncludedRouter`` during CORS preflight requests and raises before the
    # application can return the required headers. Explicit workflow spans and
    # outbound HTTPX spans still provide the operational traces used here.
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)


def workflow_span(run_id: str, dispatch_id: str):
    try:
        from opentelemetry import trace
    except ImportError:
        return nullcontext()
    tracer = trace.get_tracer("terraforge.workflow")
    return tracer.start_as_current_span(
        "terraforge.workflow.execute",
        attributes={"terraforge.run_id": run_id, "terraforge.dispatch_id": dispatch_id},
    )
