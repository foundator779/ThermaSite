from __future__ import annotations

from typing import Protocol

from terraforge.contracts.models import AcquisitionResult, DatasetRequest


class ClimateConnector(Protocol):
    dataset_id: str

    def validate_request(self, request: DatasetRequest) -> None: ...

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult: ...

    async def metadata(self) -> dict: ...
