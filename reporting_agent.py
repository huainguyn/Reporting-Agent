"""Reporting Agent: turns Coordinator Agent output into a readable report."""
from __future__ import annotations
from typing import Any, TypedDict
from pathlib import Path
import json

try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    StateGraph = None
    END = "__END__"
    LANGGRAPH_AVAILABLE = False


class ReportingState(TypedDict, total=False):
    raw_input: dict[str, Any]
    normalized: dict[str, Any]
    result: dict[str, Any]
    error: str


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_coordinator_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept coordinator envelope or a direct coordinator result.

    Expected recommended contract:
      {project_id, run_id, status, summary, findings, recommendations,
       consistency_result, metadata}
    Unknown fields are preserved in `coordinator_raw` for traceability.
    """
    if not isinstance(payload, dict):
        raise ValueError("Input phải là một JSON object từ Coordinator Agent.")

    # Some orchestrators wrap the actual result in `coordinator_output` or `result`.
    root = payload.get("coordinator_output", payload.get("result", payload))
    if not isinstance(root, dict):
        raise ValueError("Trường coordinator_output/result phải là JSON object.")

    consistency = root.get("consistency_result", root.get("consistency", {}))
    if not isinstance(consistency, dict):
        consistency = {}
    findings = root.get("findings", root.get("issues", consistency.get("issues", consistency.get("findings", []))))
    recommendations = root.get("recommendations", root.get("recommendation_result", []))
    if isinstance(recommendations, dict):
        recommendations = recommendations.get("recommendations", [])

    return {
        "project_id": str(root.get("project_id", consistency.get("project_id", "UNKNOWN"))),
        "run_id": str(root.get("run_id", consistency.get("run_id", "UNKNOWN"))),
        "project_name": root.get("project_name", root.get("project", "Software Project")),
        "status": str(root.get("status", root.get("overall_status", consistency.get("status", "RECEIVED")))),
        "summary": root.get("summary", root.get("coordinator_summary", "Coordinator Agent đã chuyển kết quả phân tích sang Reporting Agent.")),
        "findings": _as_list(findings),
        "recommendations": _as_list(recommendations),
        "unresolved_items": _as_list(root.get("unresolved_items", consistency.get("unresolved_items", []))),
        "metadata": root.get("metadata", {}),
        "coordinator_raw": root,
    }


def _field(item: Any, *keys: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        for key in keys:
            if item.get(key) is not None:
                return item[key]
    return default


def _status_counts(findings: list) -> dict[str, int]:
    counts = {"VIOLATION": 0, "REVIEW": 0, "COMPLIANT": 0, "OTHER": 0}
    for item in findings:
        status = str(_field(item, "status", "issue_status", default="OTHER")).upper()
        counts[status if status in counts else "OTHER"] += 1
    return counts


def build_report(data: dict[str, Any]) -> dict[str, Any]:
    findings = data["findings"]
    recs = data["recommendations"]
    counts = _status_counts(findings)
    lines = [
        f"# Báo cáo phân tích kiến trúc phần mềm — {data['project_name']}", "",
        f"- **Project ID:** `{data['project_id']}`",
        f"- **Run ID:** `{data['run_id']}`",
        f"- **Trạng thái từ Coordinator:** `{data['status']}`", "",
        "## 1. Tóm tắt điều hành", "", str(data["summary"]), "",
        "## 2. Thống kê kết quả", "",
        f"- Tổng số findings: **{len(findings)}**",
        f"- Vi phạm (VIOLATION): **{counts['VIOLATION']}**",
        f"- Cần xem xét (REVIEW): **{counts['REVIEW']}**",
        f"- Tuân thủ (COMPLIANT): **{counts['COMPLIANT']}**", "",
        "## 3. Findings", ""
    ]
    if not findings:
        lines.append("Coordinator không chuyển findings nào.")
    for i, item in enumerate(findings, 1):
        issue_id = _field(item, "issue_id", "finding_id", "id", default=f"FINDING-{i}")
        status = _field(item, "status", "issue_status", default="UNKNOWN")
        source = _field(item, "source_module", "source", "source_component", default="N/A")
        target = _field(item, "target_module", "target", "target_component", default="N/A")
        desc = _field(item, "description", "problem_summary", "message", default="Không có mô tả chi tiết.")
        confidence = _field(item, "confidence", default=None)
        lines += [f"### {i}. {issue_id} — {status}", "", f"- **Dependency:** `{source}` → `{target}`", f"- **Mô tả:** {desc}"]
        if confidence is not None:
            lines.append(f"- **Confidence:** {confidence}")
        rule = _field(item, "rule_description", "violated_rule", "rule", default="")
        if rule:
            lines.append(f"- **Quy tắc liên quan:** {rule}")
        evidence = _as_list(_field(item, "evidence", default=[]))
        if evidence:
            lines.append("- **Evidence:**")
            for ev in evidence:
                if isinstance(ev, dict):
                    loc = ev.get("file_path", "")
                    if ev.get("line_start") is not None:
                        loc += f":{ev['line_start']}"
                    lines.append(f"  - `{loc}` — {ev.get('description', '')}")
                else:
                    lines.append(f"  - {ev}")
        lines.append("")

    lines += ["## 4. Đề xuất xử lý", ""]
    if not recs:
        lines.append("Coordinator không chuyển recommendation nào.")
    for i, rec in enumerate(recs, 1):
        rid = _field(rec, "recommendation_id", "id", default=f"REC-{i}")
        title = _field(rec, "title", "approach", default="Recommendation")
        priority = _field(rec, "priority", default="N/A")
        lines += [f"### {i}. {rid} — {title}", "", f"- **Priority:** {priority}"]
        summary = _field(rec, "problem_summary", "description", default="")
        if summary:
            lines.append(f"- **Vấn đề:** {summary}")
        action = _field(rec, "recommended_action", "action", default={})
        if isinstance(action, dict):
            approach = action.get("approach", "")
            if approach:
                lines.append(f"- **Hướng xử lý:** {approach}")
            for step in _as_list(action.get("steps")):
                lines.append(f"  - {step}")
        elif action:
            lines.append(f"- **Hướng xử lý:** {action}")
        for step in _as_list(_field(rec, "steps", default=[])):
            lines.append(f"  - {step}")
        lines.append("")

    lines += ["## 5. Các nội dung chưa được giải quyết", ""]
    unresolved = data["unresolved_items"]
    lines.extend([f"- {x}" for x in unresolved] if unresolved else ["Không có nội dung tồn đọng được Coordinator cung cấp."])
    lines += ["", "## 6. Phạm vi và lưu ý", "", "Báo cáo này được tổng hợp từ dữ liệu do Coordinator Agent cung cấp. Reporting Agent không tự chạy lại phân tích kiến trúc, không xác minh độc lập findings và không tự sửa mã nguồn. Các kết luận trong báo cáo phụ thuộc vào độ đầy đủ/chính xác của dữ liệu đầu vào.", ""]

    graph = ["flowchart TD", "    C[Coordinator Agent output] --> R[Reporting Agent]", "    R --> S[Summary]", "    R --> F[Findings]", "    R --> A[Recommendations]", "    R --> O[Final report]"]
    for i, item in enumerate(findings, 1):
        status = str(_field(item, "status", "issue_status", default="Finding"))
        graph.insert(-1, f'    F --> F{i}["{i}. {status}"]')
    return {
        "project_id": data["project_id"], "run_id": data["run_id"],
        "agent_name": "ReportingAgent", "status": "SUCCESS",
        "statistics": {"total_findings": len(findings), **counts, "total_recommendations": len(recs)},
        "report_markdown": "\n".join(lines), "graph_mermaid": "\n".join(graph),
        "source": "CoordinatorAgent", "unresolved_items": unresolved,
    }


def node_validate(state: ReportingState) -> dict:
    try:
        return {"normalized": normalize_coordinator_output(state.get("raw_input", {})), "error": ""}
    except Exception as exc:
        return {"error": str(exc)}


def node_generate(state: ReportingState) -> dict:
    return {"result": build_report(state["normalized"])}


def node_failed(state: ReportingState) -> dict:
    return {"result": {"agent_name": "ReportingAgent", "status": "FAILED", "error": state.get("error", "Invalid input")}}


class _FallbackGraph:
    def invoke(self, initial: dict[str, Any]) -> dict[str, Any]:
        state = dict(initial)
        state.update(node_validate(state))
        state.update(node_failed(state) if state.get("error") else node_generate(state))
        return state


def build_graph():
    if not LANGGRAPH_AVAILABLE:
        return _FallbackGraph()
    graph = StateGraph(ReportingState)
    graph.add_node("validate_coordinator_output", node_validate)
    graph.add_node("generate_report", node_generate)
    graph.add_node("failed", node_failed)
    graph.set_entry_point("validate_coordinator_output")
    graph.add_conditional_edges("validate_coordinator_output", lambda s: "failed" if s.get("error") else "generate_report", {"failed": "failed", "generate_report": "generate_report"})
    graph.add_edge("generate_report", END)
    graph.add_edge("failed", END)
    return graph.compile()


class ReportingAgent:
    """Reporting node called after Coordinator Agent in the parent workflow."""
    def __init__(self):
        self.graph = build_graph()

    def run(self, coordinator_output: dict[str, Any]) -> dict[str, Any]:
        return self.graph.invoke({"raw_input": coordinator_output})["result"]

    def save_artifacts(self, result: dict[str, Any], output_dir: str = "reports") -> dict[str, str]:
        if result.get("status") != "SUCCESS":
            raise ValueError(result.get("error", "Cannot save failed report"))
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{result['project_id']}_{result['run_id']}".replace("/", "_").replace("\\", "_")
        md = folder / f"{stem}.md"
        mmd = folder / f"{stem}.mmd"
        js = folder / f"{stem}.json"
        md.write_text(result["report_markdown"], encoding="utf-8")
        mmd.write_text(result["graph_mermaid"], encoding="utf-8")
        js.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"markdown": str(md), "mermaid": str(mmd), "json": str(js)}
