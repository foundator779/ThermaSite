from __future__ import annotations

from enum import StrEnum


class ToolCapability(StrEnum):
    MODEL_DECISION = "model_decision"
    REGISTRY_READ = "registry_read"
    NETWORK_ACQUISITION = "network_acquisition"
    ARTIFACT_READ = "artifact_read"
    ARTIFACT_WRITE = "artifact_write"
    RESTRICTED_EXECUTION = "restricted_execution"
    NOTIFICATION_DELIVERY = "notification_delivery"


POLICY: dict[str, frozenset[ToolCapability]] = {
    "ADKResearchPlanner": frozenset({ToolCapability.MODEL_DECISION}),
    "ADKScientificReviewer": frozenset(
        {ToolCapability.MODEL_DECISION, ToolCapability.ARTIFACT_READ}
    ),
    "ADKOperationalActionAgent": frozenset({ToolCapability.MODEL_DECISION}),
    "DatasetDiscoveryAgent": frozenset({ToolCapability.REGISTRY_READ}),
    "AcquisitionAgent": frozenset(
        {ToolCapability.NETWORK_ACQUISITION, ToolCapability.ARTIFACT_WRITE}
    ),
    "DataQualityAgent": frozenset({ToolCapability.ARTIFACT_READ}),
    "CrossDatasetHarmonizationAgent": frozenset(
        {ToolCapability.ARTIFACT_READ, ToolCapability.ARTIFACT_WRITE}
    ),
    "CodeGenerationAgent": frozenset({ToolCapability.ARTIFACT_WRITE}),
    "AnalysisExecutor": frozenset(
        {ToolCapability.RESTRICTED_EXECUTION, ToolCapability.ARTIFACT_WRITE}
    ),
    "ExecutionRepairAgent": frozenset({ToolCapability.ARTIFACT_WRITE}),
    "ScientificValidationAgent": frozenset({ToolCapability.ARTIFACT_READ}),
    "ProvenanceReportingAgent": frozenset(
        {ToolCapability.ARTIFACT_READ, ToolCapability.ARTIFACT_WRITE}
    ),
    "NotificationAgent": frozenset({ToolCapability.NOTIFICATION_DELIVERY}),
}


class ToolPolicy:
    def require(self, agent: str, capability: ToolCapability) -> None:
        if capability not in POLICY.get(agent, frozenset()):
            raise PermissionError(f"{agent} is not permitted to use {capability.value}")
