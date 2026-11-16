"""Reporting Agent orchestration (LangGraph when installed, deterministic fallback otherwise)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict
import json
import re

from .normalizer import normalize_coordinator_output, InputValidationError
from .analyzer import analyze_normalized
from .renderers import render_markdown, render_mermaid, render_findings_csv, render_recommendations_csv

try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:  # A standard-library fallback keeps local/demo execution simple.
    StateGraph = None
    END = "__END__"
    LANGGRAPH_AVAILABLE = False


class ReportingState(TypedDict, total=False):
    raw_input: dict[str, Any]
    normalized: dict[str, Any]
    analysis: dict[str, Any]
    result: dict[str, Any]
    generated_at: str
    error: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "unknown")).strip("-._")
    return (text or "unknown")[:70]


def node_normalize(state: ReportingState) -> dict[str, Any]:
    try:
        normalized = normalize_coordinator_output(state.get("raw_input", {}))
        return {"normalized": normalized, "error": ""}
    except (InputValidationError, TypeError, ValueError) as exc:
        return {"error": str(exc)}


def node_analyze(state: ReportingState) -> dict[str, Any]:
    return {"analysis": analyze_normalized(state["normalized"])}


def node_render(state: ReportingState) -> dict[str, Any]:
    data = state["normalized"]
    analysis = state["analysis"]
    generated_at = state.get("generated_at", _utc_now())
    result = {
        "schema_version": "1.0.0",
        "agent_name": "ReportingAgent",
        "status": "SUCCESS",
        "generated_at": generated_at,
        "project": {
            "project_id": data["project_id"],
            "project_name": data["project_name"],
            "run_id": data["run_id"],
        },
        "source": {
            "agent": "CoordinatorAgent",
            "coordinator_status": data["coordinator_status"],
            "input_sha256": data["input_sha256"],
        },
        "overall_assessment": analysis["overall_assessment"],
        "coordinator_summary": data["coordinator_summary"],
        "statistics": analysis["statistics"],
        "findings": analysis["findings"],
        "recommendations": analysis["recommendations"],
        "generated_guidance": analysis["generated_guidance"],
        "unlinked_recommendations": analysis["unlinked_recommendations"],
        "unresolved_items": data["unresolved_items"],
        "metadata": data["metadata"],
        "warnings": analysis["warnings"],
    }
    result["report_markdown"] = render_markdown(data, analysis, generated_at)
    result["graph_mermaid"] = render_mermaid(data, analysis)
    result["findings_csv"] = render_findings_csv(analysis["findings"])
    result["recommendations_csv"] = render_recommendations_csv(analysis["recommendations"])
    return {"result": result}


def node_failed(state: ReportingState) -> dict[str, Any]:
    return {"result": {
        "schema_version": "1.0.0",
        "agent_name": "ReportingAgent",
        "status": "FAILED",
        "generated_at": state.get("generated_at", _utc_now()),
        "error": state.get("error", "Invalid Coordinator input"),
        "findings": [],
        "recommendations": [],
        "warnings": [],
    }}


def _route_after_normalize(state: ReportingState) -> str:
    return "failed" if state.get("error") else "analyze"


class _SequentialFallbackGraph:
    def invoke(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        state: ReportingState = dict(initial_state)  # type: ignore[assignment]
        state.update(node_normalize(state))
        if state.get("error"):
            state.update(node_failed(state))
            return state
        state.update(node_analyze(state))
        state.update(node_render(state))
        return state


def build_graph():
    """Build the internal Reporting Agent workflow."""
    if not LANGGRAPH_AVAILABLE:
        return _SequentialFallbackGraph()

    workflow = StateGraph(ReportingState)
    workflow.add_node("normalize_coordinator_output", node_normalize)
    workflow.add_node("analyze_findings", node_analyze)
    workflow.add_node("render_report", node_render)
    workflow.add_node("failed", node_failed)
    workflow.set_entry_point("normalize_coordinator_output")
    workflow.add_conditional_edges(
        "normalize_coordinator_output",
        _route_after_normalize,
        {"analyze": "analyze_findings", "failed": "failed"},
    )
    workflow.add_edge("analyze_findings", "render_report")
    workflow.add_edge("render_report", END)
    workflow.add_edge("failed", END)
    return workflow.compile()


class ReportingAgent:
    """Independent Reporting Agent called after Coordinator Agent.

    The class accepts a JSON-compatible Coordinator result and returns a
    structured result plus Markdown, Mermaid and CSV representations.
    It does not run architecture/source-code analysis and does not modify code.
    """
    def __init__(self) -> None:
        self.graph = build_graph()

    def run(self, coordinator_output: dict[str, Any]) -> dict[str, Any]:
        state = self.graph.invoke({"raw_input": coordinator_output, "generated_at": _utc_now()})
        return state["result"]

    def save_artifacts(self, result: dict[str, Any], output_dir: str | Path = "reports") -> dict[str, str]:
        if result.get("status") != "SUCCESS":
            raise ValueError(result.get("error", "Không thể lưu báo cáo do đầu vào không hợp lệ."))
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        project = result.get("project", {})
        stem = f"{_slug(project.get('project_id'))}_{_slug(project.get('run_id'))}"
        artifacts = {
            "markdown": folder / f"{stem}_report.md",
            "mermaid": folder / f"{stem}_graph.mmd",
            "json": folder / f"{stem}_result.json",
            "findings_csv": folder / f"{stem}_findings.csv",
            "recommendations_csv": folder / f"{stem}_recommendations.csv",
        }
        artifacts["markdown"].write_text(result["report_markdown"], encoding="utf-8")
        artifacts["mermaid"].write_text(result["graph_mermaid"], encoding="utf-8")
        artifacts["json"].write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        artifacts["findings_csv"].write_text(result["findings_csv"], encoding="utf-8-sig", newline="")
        artifacts["recommendations_csv"].write_text(result["recommendations_csv"], encoding="utf-8-sig", newline="")
        return {name: str(path) for name, path in artifacts.items()}
