from __future__ import annotations

import pytest
import respx
from httpx import Response

from terraforge.observability.notifications import deliver_webhook


@pytest.mark.asyncio
@respx.mock
async def test_webhook_retries_transient_failures_with_incident_idempotency_key():
    route = respx.post("https://field.example.org/incidents").mock(
        side_effect=[Response(503), Response(429), Response(202)]
    )

    delivery = await deliver_webhook(
        "https://field.example.org/incidents",
        {"event": "habiwatch.monitoring.incident"},
        attempts=3,
        idempotency_key="incident-123",
    )

    assert delivery["status"] == "delivered"
    assert delivery["attempt_count"] == 3
    assert len(route.calls) == 3
    assert all(call.request.headers["Idempotency-Key"] == "incident-123" for call in route.calls)


@pytest.mark.asyncio
async def test_webhook_rejects_private_targets_without_raising():
    delivery = await deliver_webhook("https://127.0.0.1/incidents", {"event": "test"}, attempts=3)

    assert delivery["status"] == "failed"
    assert delivery["error"] == "ValueError"
    assert delivery["attempt_count"] == 0
