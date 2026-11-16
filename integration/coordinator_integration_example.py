"""Example only: connect the final Coordinator node to Reporting Agent.

Replace `coordinator_output` with the actual key produced by your Coordinator
state. This file is a reference integration, not a runnable copy of the team's
Coordinator graph.
"""
from typing import Any, TypedDict
from reporting_agent import ReportingAgent

reporting_agent = ReportingAgent()


class ProjectWorkflowState(TypedDict, total=False):
    coordinator_output: dict[str, Any]
    reporting_result: dict[str, Any]


def reporting_node(state: ProjectWorkflowState) -> dict[str, Any]:
    output = state.get("coordinator_output")
    if not isinstance(output, dict):
        return {"reporting_result": {
            "agent_name": "ReportingAgent",
            "status": "FAILED",
            "error": "Coordinator output missing or is not a JSON object.",
        }}
    return {"reporting_result": reporting_agent.run(output)}


# In the parent LangGraph builder:
# builder.add_node("reporting", reporting_node)
# builder.add_edge("coordinator", "reporting")
# builder.add_edge("reporting", END)
