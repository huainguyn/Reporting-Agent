"""Render normalized reporting results as Markdown, Mermaid and CSV."""
from __future__ import annotations
import csv
import io
import json
import re
from typing import Any


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _code(value: Any) -> str:
    return "`" + str(value or "N/A").replace("`", "'") + "`"


def _confidence(value: Any) -> str:
    return "Không có" if value is None else f"{float(value) * 100:.1f}%"


def render_markdown(data: dict[str, Any], analysis: dict[str, Any], generated_at: str) -> str:
    stats = analysis["statistics"]
    findings = analysis["findings"]
    recs = analysis["recommendations"]
    assessment_labels = {
        "ATTENTION_REQUIRED": "Cần xử lý vi phạm",
        "REVIEW_REQUIRED": "Cần xem xét thêm",
        "COMPLIANT": "Không ghi nhận vi phạm trong dữ liệu được cung cấp",
        "NO_FINDINGS_REPORTED": "Không có findings được chuyển sang",
        "PARTIAL_DATA": "Dữ liệu phân tích chưa đầy đủ",
        "SOURCE_FAILED": "Coordinator báo lỗi",
        "INSUFFICIENT_DATA": "Dữ liệu chưa đủ để kết luận",
    }
    lines = [
        f"# Báo cáo phân tích kiến trúc — {data['project_name']}", "",
        f"- **Project ID:** {_code(data['project_id'])}",
        f"- **Run ID:** {_code(data['run_id'])}",
        f"- **Coordinator status:** {_code(data['coordinator_status'])}",
        f"- **Reporting assessment:** **{assessment_labels.get(analysis['overall_assessment'], analysis['overall_assessment'])}**",
        f"- **Generated at (UTC):** {generated_at}",
        f"- **Input SHA-256:** {_code(data['input_sha256'])}", "",
        "> Báo cáo được tổng hợp từ output của Coordinator Agent. Reporting Agent không tự quét mã nguồn, không xác minh độc lập findings và không tự sửa kiến trúc.", "",
        "## 1. Tóm tắt điều hành", "", data["coordinator_summary"], "",
        "### Chỉ số chính", "",
        "| Chỉ số | Giá trị |", "|---|---:|",
        f"| Tổng findings | {stats['total_findings']} |",
        f"| Violation | {stats['findings_by_status']['VIOLATION']} |",
        f"| Review | {stats['findings_by_status']['REVIEW']} |",
        f"| Compliant | {stats['findings_by_status']['COMPLIANT']} |",
        f"| Unknown / chưa phân loại | {stats['findings_by_status']['UNKNOWN']} |",
        f"| Recommendations từ Coordinator | {stats['total_recommendations']} |",
        f"| Evidence items | {stats['total_evidence_items']} |",
        f"| Findings có evidence | {stats['findings_with_evidence']} |",
        f"| Violation có recommendation liên kết | {stats['violations_with_recommendation']} |",
        f"| Độ phủ recommendation cho violation | {'N/A' if stats['violation_recommendation_coverage_percent'] is None else str(stats['violation_recommendation_coverage_percent']) + '%'} |", "",
        "## 2. Findings", "",
    ]

    if not findings:
        lines.append("Coordinator không chuyển findings. Không thể suy luận rằng hệ thống chắc chắn không có vấn đề; cần kiểm tra phạm vi và trạng thái phân tích ở phía Coordinator.")
    for idx, finding in enumerate(findings, 1):
        status = finding["status"]
        lines += [
            f"### {idx}. {finding['finding_id']} — {status}", "",
            f"- **Severity:** {finding['severity']}",
            f"- **Disposition:** {finding['reporting_disposition']}",
            f"- **Title:** {finding['title']}",
            f"- **Mô tả:** {finding['description']}",
            f"- **Dependency:** {_code(finding['source_component'] or 'N/A')} → {_code(finding['target_component'] or 'N/A')}",
            f"- **Dependency type:** {finding['dependency_type'] or 'Không có dữ liệu'}",
            f"- **Architecture rule:** {finding['rule_id'] or 'N/A'} — {finding['rule_description'] or 'Không có mô tả rule'}",
            f"- **Confidence:** {_confidence(finding['confidence'])}",
            f"- **Recommendations liên kết:** {', '.join(finding['recommendation_ids']) if finding['recommendation_ids'] else 'Chưa có'}",
        ]
        if finding.get("reporting_note"):
            lines.append(f"- **Ghi chú của Reporting Agent:** {finding['reporting_note']}")
        lines.append("")
        lines.append("**Evidence:**")
        if finding["evidence"]:
            for evidence in finding["evidence"]:
                location = evidence.get("file_path") or "Vị trí không được cung cấp"
                if evidence.get("line_start") is not None:
                    location += f":{evidence['line_start']}"
                    if evidence.get("line_end") is not None and evidence["line_end"] != evidence["line_start"]:
                        location += f"-{evidence['line_end']}"
                detail = evidence.get("description") or "Không có mô tả evidence"
                symbol = f" ({evidence['symbol']})" if evidence.get("symbol") else ""
                lines.append(f"- {_code(location)}{symbol}: {detail}")
        else:
            lines.append("- Coordinator không cung cấp evidence cho finding này.")
        if finding.get("unresolved_items"):
            lines.append("\n**Nội dung cần làm rõ:**")
            lines.extend(f"- {item}" for item in finding["unresolved_items"])
        lines.append("")

    lines += ["## 3. Recommendations do Coordinator cung cấp", ""]
    if not recs:
        lines.append("Coordinator không cung cấp recommendation nào.")
    for idx, rec in enumerate(recs, 1):
        links = rec.get("related_finding_ids", [])
        lines += [
            f"### {idx}. {rec['recommendation_id']} — {rec['title']}", "",
            f"- **Finding liên quan:** {', '.join(links) if links else 'Chưa liên kết'}",
            f"- **Priority:** {rec['priority']}",
            f"- **Mô tả vấn đề:** {rec['description'] or 'Không có'}",
            f"- **Hướng xử lý:** {rec['action'] or 'Coordinator chưa cung cấp'}",
        ]
        if rec["steps"]:
            lines.append("- **Các bước:**")
            lines.extend(f"  {step_no}. {step}" for step_no, step in enumerate(rec["steps"], 1))
        if rec["expected_benefit"]:
            lines.append(f"- **Lợi ích kỳ vọng:** {rec['expected_benefit']}")
        if rec["risks"]:
            lines.append("- **Rủi ro:** " + "; ".join(rec["risks"]))
        lines.append(f"- **Cần human review:** {'Có' if rec['requires_human_review'] else 'Không'}")
        lines.append("")

    lines += ["## 4. Hướng theo dõi do Reporting Agent tạo", "", "> Đây là quy tắc theo dõi ở tầng báo cáo, không phải phương án sửa kỹ thuật và không thay thế recommendation từ Coordinator.", ""]
    guidance = analysis["generated_guidance"]
    if not guidance:
        lines.append("Không phát sinh hướng theo dõi bổ sung theo các quy tắc báo cáo.")
    for item in guidance:
        lines.append(f"- **{item['guidance_id']}** — `{item['related_finding_id']}` — **{item['type']}**: {item['message']}")
    lines += ["", "## 5. Nội dung chưa được giải quyết", ""]
    unresolved = data["unresolved_items"]
    if unresolved:
        lines.extend(f"- {item}" for item in unresolved)
    else:
        lines.append("Coordinator không cung cấp unresolved item ở cấp run.")

    lines += ["", "## 6. Chất lượng dữ liệu và cảnh báo", ""]
    if analysis["warnings"]:
        lines.extend(f"- {warning}" for warning in analysis["warnings"])
    else:
        lines.append("Không phát hiện cảnh báo cấu trúc đáng chú ý trong quá trình chuẩn hóa.")
    if analysis["unlinked_recommendations"]:
        lines.append("\n**Recommendations chưa liên kết được với finding:**")
        lines.extend(f"- {rec['recommendation_id']} — {rec['title']}" for rec in analysis["unlinked_recommendations"])

    lines += [
        "", "## 7. Phương pháp và giới hạn", "",
        "1. Dữ liệu findings, evidence, rule và recommendations được lấy từ Coordinator Agent.",
        "2. Reporting Agent chuẩn hóa tên trường, thống kê trạng thái/mức độ, liên kết recommendation với finding và kết xuất báo cáo.",
        "3. Khi Coordinator không cung cấp severity, báo cáo gán mức mặc định theo trạng thái để phục vụ sắp xếp: VIOLATION → HIGH, REVIEW → MEDIUM, COMPLIANT → INFO. Đây là mức mặc định báo cáo, không phải đánh giá tác động độc lập.",
        "4. Reporting Agent không tự tạo technical fix. Các mục trong phần hướng theo dõi chỉ là yêu cầu tiếp theo ở mức quy trình.",
        "5. Kết luận phụ thuộc vào tính đầy đủ, chính xác và phạm vi dữ liệu đầu vào.", "",
        "---", "*Generated by Reporting Agent.*", "",
    ]
    return "\n".join(lines)


def _mermaid_escape(text: str) -> str:
    return str(text or "").replace('"', "'").replace("\n", " ").replace("[", "(").replace("]", ")")[:110]


def render_mermaid(data: dict[str, Any], analysis: dict[str, Any]) -> str:
    lines = [
        "flowchart TD",
        '    C["Coordinator Agent output"] --> R["Reporting Agent"]',
        '    R --> S["Normalize and validate"]',
        '    S --> A["Analyze and map findings"]',
        '    A --> O["Report / Graph / CSV / JSON"]',
        '    subgraph FINDINGS["Coordinator findings"]',
    ]
    findings = analysis["findings"]
    if not findings:
        lines.append('        NOF["No findings supplied"]')
    for i, finding in enumerate(findings, 1):
        node_id = f"F{i}"
        label = f"{finding['finding_id']} | {finding['status']} | {finding['severity']}"
        lines.append(f'        {node_id}["{_mermaid_escape(label)}"]')
        lines.append(f"        A --> {node_id}")
    lines.append("    end")
    if analysis["recommendations"]:
        lines.append('    subgraph RECOMMENDATIONS["Coordinator recommendations"]')
        for i, rec in enumerate(analysis["recommendations"], 1):
            rid = f"REC{i}"
            lines.append(f'        {rid}["{_mermaid_escape(rec["recommendation_id"] + " | " + rec["title"])}"]')
        lines.append("    end")
        id_to_node = {f["finding_id"]: f"F{i}" for i, f in enumerate(findings, 1)}
        rec_node_by_id = {r["recommendation_id"]: f"REC{i}" for i, r in enumerate(analysis["recommendations"], 1)}
        for rec in analysis["recommendations"]:
            for fid in rec.get("related_finding_ids", []):
                if fid in id_to_node and rec["recommendation_id"] in rec_node_by_id:
                    lines.append(f"    {id_to_node[fid]} -. related .-> {rec_node_by_id[rec['recommendation_id']]}")
    return "\n".join(lines) + "\n"


def _csv_safe(value: Any) -> Any:
    """Avoid spreadsheet formula execution when CSV is opened in Excel-like tools."""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def render_findings_csv(findings: list[dict[str, Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=[
        "finding_id", "status", "severity", "confidence", "title", "description",
        "source_component", "target_component", "dependency_type", "rule_id",
        "rule_description", "recommendation_ids", "evidence_count", "reporting_disposition",
    ])
    writer.writeheader()
    for f in findings:
        writer.writerow({
            key: _csv_safe(value) for key, value in {
                **{key: f.get(key, "") for key in writer.fieldnames if key not in {"recommendation_ids", "evidence_count"}},
                "recommendation_ids": ";".join(f.get("recommendation_ids", [])),
                "evidence_count": len(f.get("evidence", [])),
            }.items()
        })
    return buffer.getvalue()


def render_recommendations_csv(recommendations: list[dict[str, Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=[
        "recommendation_id", "related_finding_ids", "title", "priority", "description",
        "action", "steps", "expected_benefit", "requires_human_review", "source",
    ])
    writer.writeheader()
    for rec in recommendations:
        writer.writerow({key: _csv_safe(value) for key, value in {
            "recommendation_id": rec.get("recommendation_id", ""),
            "related_finding_ids": ";".join(rec.get("related_finding_ids", [])),
            "title": rec.get("title", ""), "priority": rec.get("priority", ""),
            "description": rec.get("description", ""), "action": rec.get("action", ""),
            "steps": " | ".join(rec.get("steps", [])),
            "expected_benefit": rec.get("expected_benefit", ""),
            "requires_human_review": rec.get("requires_human_review", True),
            "source": rec.get("source", "COORDINATOR"),
        }.items()})
    return buffer.getvalue()
