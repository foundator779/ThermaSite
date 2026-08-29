from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from google.cloud import pubsub_v1

from terraforge.contracts.models import RunEvent
from terraforge.settings import Settings

logger = logging.getLogger("terraforge.events")


class EventPublisher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._publisher = pubsub_v1.PublisherClient() if settings.cloud_enabled else None
        self._topic = (
            self._publisher.topic_path(settings.gcp_project_id, settings.pubsub_topic)
            if self._publisher
            else None
        )

    async def publish(self, run_id: UUID, event: RunEvent) -> None:
        structured = {"run_id": str(run_id), **event.model_dump(mode="json")}
        logger.info(json.dumps(structured, separators=(",", ":")))
        if self._publisher and self._topic:
            future = self._publisher.publish(
                self._topic,
                json.dumps(structured).encode(),
                run_id=str(run_id),
                event_type=event.type,
            )
            await asyncio.to_thread(future.result, timeout=10)
