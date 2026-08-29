import pytest

from terraforge.orchestration.policy import ToolCapability, ToolPolicy


def test_agent_tool_policy_allows_scoped_tools_and_denies_privilege_crossing():
    policy = ToolPolicy()
    policy.require("AcquisitionAgent", ToolCapability.NETWORK_ACQUISITION)
    with pytest.raises(PermissionError, match="not permitted"):
        policy.require("ScientificValidationAgent", ToolCapability.NETWORK_ACQUISITION)
    with pytest.raises(PermissionError, match="not permitted"):
        policy.require("GoogleADKCoordinator", ToolCapability.RESTRICTED_EXECUTION)
