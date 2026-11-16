"""Deterministic reporting analysis built only from Coordinator-provided data."""
from __future__ import annotations
from collections import Counter, defaultdict
from typing import Any


STATUS_ORDER = ("VIOLATION", "REVIEW", "COMPLIANT", "UNKNOWN")
SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "UNSPECIFIED")


def _derived_severity(finding: dict[str, Any]) -> str:
    given = finding.get("severity", "UNSPECIFIED")
    if given != "UNSPECIFIED":
        return given
    return {"VIOLATION": "HIGH", "REVIEW": "MEDIUM", "COMPLIANT": "INFO"}.get(finding.get("status"), "UNSPECIFIED")


def analyze_normalized(data: dict[str, Any]) -> dict[str, Any]:
    findings = data["findings"]
    recommendations = data["recommendations"]
    warnings = list(data.get("normalization_warnings", []))

    findings_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        findings_by_id[finding["finding_id"]].append(finding)
    duplicated = [fid for fid, group in findings_by_id.items() if len(group) > 1]
    if duplicated:
        warnings.append("Finding ID bị trùng: " + ", ".join(duplicated) + ". Các liên kết theo ID có thể không duy nhất.")

    recs_by_finding: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unlinked_recommendations: list[dict[str, Any]] = []
    known_ids = set(findings_by_id)
    recommendation_ids = [r.get("recommendation_id", "") for r in recommendations]
    duplicate_recommendation_ids = sorted({rid for rid in recommendation_ids if rid and recommendation_ids.count(rid) > 1})
    if duplicate_recommendation_ids:
        warnings.append("Recommendation ID bị trùng: " + ", ".join(duplicate_recommendation_ids) + ".")
    for recommendation in recommendations:
        links = recommendation.get("related_finding_ids", [])
        if not links:
            unlinked_recommendations.append(recommendation)
            warnings.append(f"Recommendation {recommendation['recommendation_id']} chưa được liên kết với finding nào.")
            continue
        valid_links = [fid for fid in links if fid in known_ids]
        invalid_links = [fid for fid in links if fid not in known_ids]
        recommendation["unresolved_finding_ids"] = invalid_links
        for fid in valid_links:
            recs_by_finding[fid].append(recommendation)
        if invalid_links:
            warnings.append(
                f"Recommendation {recommendation['recommendation_id']} tham chiếu finding không tồn tại: {', '.join(invalid_links)}."
            )
        if not valid_links:
            unlinked_recommendations.append(recommendation)

    enriched_findings: list[dict[str, Any]] = []
    for finding in findings:
        enriched = dict(finding)
        enriched["severity"] = _derived_severity(finding)
        linked = recs_by_finding.get(finding["finding_id"], [])
        enriched["recommendation_ids"] = [r["recommendation_id"] for r in linked]
        status = finding.get("status")
        if status == "VIOLATION":
            enriched["reporting_disposition"] = "REMEDIATION_REQUIRED"
        elif status == "REVIEW":
            enriched["reporting_disposition"] = "HUMAN_REVIEW_REQUIRED"
        elif status == "COMPLIANT":
            enriched["reporting_disposition"] = "NO_ACTION_REQUIRED"
        else:
            enriched["reporting_disposition"] = "CLASSIFICATION_REQUIRED"
        if status == "VIOLATION" and not linked:
            enriched["reporting_note"] = "Coordinator chưa cung cấp recommendation gắn với finding này. Cần nhóm phụ trách đánh giá và lập phương án xử lý; Reporting Agent không tự suy diễn cách sửa kỹ thuật."
        elif status == "REVIEW":
            enriched["reporting_note"] = "Cần xác minh thêm bằng chứng hoặc quy tắc liên quan trước khi kết luận."
        else:
            enriched["reporting_note"] = ""
        enriched_findings.append(enriched)

    status_counts = Counter(f.get("status", "UNKNOWN") for f in findings)
    severity_counts = Counter(f.get("severity", "UNSPECIFIED") if f.get("severity") != "UNSPECIFIED" else _derived_severity(f) for f in findings)
    evidence_count = sum(len(f.get("evidence", [])) for f in findings)
    findings_with_evidence = sum(bool(f.get("evidence")) for f in findings)
    violation_ids = {f["finding_id"] for f in findings if f.get("status") == "VIOLATION"}
    violations_with_recommendation = sum(1 for fid in violation_ids if recs_by_finding.get(fid))
    coverage = (violations_with_recommendation / len(violation_ids) * 100.0) if violation_ids else None

    coordinator_status = data.get("coordinator_status", "RECEIVED")
    if coordinator_status in {"FAILED", "ERROR"}:
        overall_assessment = "SOURCE_FAILED"
    elif coordinator_status in {"PARTIAL", "PARTIAL_SUCCESS", "INCOMPLETE"}:
        overall_assessment = "PARTIAL_DATA"
    elif status_counts.get("UNKNOWN", 0):
        overall_assessment = "INSUFFICIENT_DATA"
    elif status_counts.get("VIOLATION", 0):
        overall_assessment = "ATTENTION_REQUIRED"
    elif status_counts.get("REVIEW", 0):
        overall_assessment = "REVIEW_REQUIRED"
    elif not findings:
        overall_assessment = "NO_FINDINGS_REPORTED"
    else:
        overall_assessment = "COMPLIANT"

    # These are reporting follow-up prompts, not generated technical fixes.
    generated_guidance: list[dict[str, Any]] = []
    linked_finding_ids = set(recs_by_finding)
    for finding in enriched_findings:
        if finding["status"] == "VIOLATION" and finding["finding_id"] not in linked_finding_ids:
            generated_guidance.append({
                "guidance_id": f"FOLLOWUP-{finding['finding_id']}",
                "related_finding_id": finding["finding_id"],
                "type": "REMEDIATION_PLANNING_REQUIRED",
                "priority": finding["severity"],
                "message": "Chưa có phương án xử lý từ Coordinator. Giao finding cho người phụ trách kiến trúc/mã nguồn để đánh giá và lập phương án có căn cứ.",
                "source": "REPORTING_AGENT_RULE",
                "is_technical_fix": False,
            })
        elif finding["status"] == "REVIEW":
            generated_guidance.append({
                "guidance_id": f"FOLLOWUP-{finding['finding_id']}",
                "related_finding_id": finding["finding_id"],
                "type": "EVIDENCE_REVIEW_REQUIRED",
                "priority": finding["severity"],
                "message": "Bổ sung hoặc xác minh evidence, phạm vi kiến trúc và rule liên quan trước khi đưa ra kết luận.",
                "source": "REPORTING_AGENT_RULE",
                "is_technical_fix": False,
            })

    statistics = {
        "total_findings": len(findings),
        "findings_by_status": {status: status_counts.get(status, 0) for status in STATUS_ORDER},
        "findings_by_severity": {severity: severity_counts.get(severity, 0) for severity in SEVERITY_ORDER},
        "total_recommendations": len(recommendations),
        "linked_recommendations": len(recommendations) - len(unlinked_recommendations),
        "unlinked_recommendations": len(unlinked_recommendations),
        "violations_with_recommendation": violations_with_recommendation,
        "violation_recommendation_coverage_percent": round(coverage, 2) if coverage is not None else None,
        "total_evidence_items": evidence_count,
        "findings_with_evidence": findings_with_evidence,
        "findings_without_evidence": len(findings) - findings_with_evidence,
        "unresolved_items": len(data.get("unresolved_items", [])),
    }

    return {
        "overall_assessment": overall_assessment,
        "statistics": statistics,
        "findings": enriched_findings,
        "recommendations": recommendations,
        "generated_guidance": generated_guidance,
        "unlinked_recommendations": unlinked_recommendations,
        "warnings": list(dict.fromkeys(warnings)),
    }
