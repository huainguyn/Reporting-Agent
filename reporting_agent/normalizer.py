"""Normalize Coordinator Agent payloads into a stable reporting contract.

The normalizer is deliberately tolerant about common field aliases, but it does
not invent technical findings or repair instructions. Unknown source fields
are retained in `metadata.coordinator_metadata` when they are JSON-compatible.
"""
from __future__ import annotations

from typing import Any
import hashlib
import json
import re


class InputValidationError(ValueError):
    """Raised when the Coordinator payload cannot be interpreted safely."""


def _first(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _normal_status(value: Any) -> str:
    raw = _as_text(value, "UNKNOWN").upper().strip().replace("-", "_").replace(" ", "_")
    aliases = {
        "PASS": "COMPLIANT", "PASSED": "COMPLIANT", "OK": "COMPLIANT",
        "CLEAN": "COMPLIANT", "CONFORMANT": "COMPLIANT", "COMPLIANCE": "COMPLIANT",
        "FAIL": "VIOLATION", "FAILED": "VIOLATION", "NON_COMPLIANT": "VIOLATION",
        "NONCOMPLIANT": "VIOLATION", "ERROR": "VIOLATION", "VIOLATES": "VIOLATION",
        "WARNING": "REVIEW", "NEEDS_REVIEW": "REVIEW", "UNCERTAIN": "REVIEW",
        "PENDING_REVIEW": "REVIEW", "INCONCLUSIVE": "REVIEW",
    }
    return aliases.get(raw, raw if raw in {"VIOLATION", "REVIEW", "COMPLIANT"} else "UNKNOWN")


def _normal_priority(value: Any) -> str:
    raw = _as_text(value, "").upper().strip().replace("-", "_").replace(" ", "_")
    aliases = {"P0": "CRITICAL", "P1": "HIGH", "P2": "MEDIUM", "P3": "LOW", "URGENT": "CRITICAL"}
    raw = aliases.get(raw, raw)
    return raw if raw in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"} else "UNSPECIFIED"


def _confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1 and number <= 100:
        number /= 100.0
    if 0 <= number <= 1:
        return round(number, 4)
    return None


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """Unwrap common transport envelopes without walking arbitrary nested data."""
    current = payload
    for key in ("coordinator_output", "coordinator_result", "output", "result", "data"):
        candidate = current.get(key)
        if candidate is not None:
            if not isinstance(candidate, dict):
                raise InputValidationError(f"Trường {key} phải là một JSON object, nhận được {type(candidate).__name__}.")
            # Prefer the nested object only when it resembles an agent result.
            if any(k in candidate for k in (
                "findings", "issues", "consistency_result", "consistency",
                "recommendations", "project_id", "run_id", "overall_status"
            )):
                current = candidate
                break
    return current


def _find_collection(root: dict[str, Any], names: tuple[str, ...], nested_names: tuple[str, ...]) -> list[Any]:
    value = _first(root, *names)
    if value is not None:
        if isinstance(value, dict):
            for name in nested_names:
                nested = value.get(name)
                if isinstance(nested, list):
                    return nested
            # A single finding/recommendation object is accepted as one record.
            return [value]
        return _as_list(value)

    # Search only well-known Coordinator result containers.
    for container_key in (
        "consistency_result", "consistency", "consistency_check_result",
        "consistency_check", "analysis_result", "aggregated_result", "results"
    ):
        container = root.get(container_key)
        if isinstance(container, dict):
            for name in names + nested_names:
                nested = container.get(name)
                if nested is not None:
                    if isinstance(nested, dict):
                        for child in nested_names:
                            if isinstance(nested.get(child), list):
                                return nested[child]
                        return [nested]
                    return _as_list(nested)
    return []


def _normalize_evidence(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in _as_list(value):
        if isinstance(entry, str):
            result.append({"file_path": entry, "line_start": None, "line_end": None, "description": ""})
            continue
        if not isinstance(entry, dict):
            result.append({"file_path": "", "line_start": None, "line_end": None, "description": _as_text(entry)})
            continue
        start = _first(entry, "line_start", "start_line", "line", "line_number")
        end = _first(entry, "line_end", "end_line")
        try:
            start = int(start) if start is not None else None
        except (TypeError, ValueError):
            start = None
        try:
            end = int(end) if end is not None else None
        except (TypeError, ValueError):
            end = None
        result.append({
            "file_path": _as_text(_first(entry, "file_path", "path", "file", "filename")),
            "line_start": start,
            "line_end": end,
            "description": _as_text(_first(entry, "description", "detail", "message")),
            "symbol": _as_text(_first(entry, "symbol", "function", "class_name")),
        })
    return result


def _normalize_finding(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {"description": _as_text(item)}
    finding_id = _as_text(_first(item, "issue_id", "finding_id", "violation_id", "id", "code"), f"FIND-{index:03d}")
    source = _as_text(_first(item, "source_module", "source_component", "source", "from", "caller"), "")
    target = _as_text(_first(item, "target_module", "target_component", "target", "to", "callee"), "")
    evidence = _normalize_evidence(_first(item, "evidence", "evidences", "locations", "code_references", default=[]))
    description = _as_text(_first(item, "description", "problem_summary", "message", "detail", "finding", "reason"), "Chưa có mô tả từ Coordinator.")
    return {
        "finding_id": finding_id,
        "status": _normal_status(_first(item, "status", "issue_status", "result", "classification")),
        "severity": _normal_priority(_first(item, "severity", "priority", "risk_level")),
        "confidence": _confidence(_first(item, "confidence", "score", "confidence_score")),
        "title": _as_text(_first(item, "title", "name"), finding_id),
        "description": description,
        "source_component": source,
        "target_component": target,
        "dependency_type": _as_text(_first(item, "dependency_type", "relation", "relationship")),
        "rule_id": _as_text(_first(item, "rule_id", "architecture_rule_id")),
        "rule_description": _as_text(_first(item, "rule_description", "violated_rule", "rule", "constraint")),
        "evidence": evidence,
        "unresolved_items": [_as_text(x) for x in _as_list(_first(item, "unresolved_items", "open_questions", default=[]))],
        "tags": [_as_text(x) for x in _as_list(item.get("tags", []))],
        "raw": item,
    }


def _normalize_recommendation(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {"description": _as_text(item)}
    action_value = _first(item, "recommended_action", "action", "remediation", "proposed_change", default={})
    if isinstance(action_value, dict):
        action = _as_text(_first(action_value, "approach", "description", "action", "summary"))
        steps = [_as_text(x) for x in _as_list(_first(action_value, "steps", "procedure", default=[]))]
    else:
        action = _as_text(action_value)
        steps = []
    steps.extend(_as_text(x) for x in _as_list(item.get("steps", [])))
    related = _first(item, "related_finding_ids", "related_finding_id", "related_issue_ids", "related_issue_id", "issue_id", "finding_id", "target_finding_id", default=[])
    related_ids = [_as_text(x) for x in _as_list(related) if _as_text(x)]
    # Preserve order while removing duplicate links.
    related_ids = list(dict.fromkeys(related_ids))
    return {
        "recommendation_id": _as_text(_first(item, "recommendation_id", "id", "recommendation_code"), f"REC-{index:03d}"),
        "related_finding_ids": related_ids,
        "title": _as_text(_first(item, "title", "name", "approach"), f"Recommendation {index}"),
        "priority": _normal_priority(_first(item, "priority", "severity", "risk_level")),
        "description": _as_text(_first(item, "problem_summary", "description", "reason", "rationale")),
        "action": action,
        "steps": steps,
        "expected_benefit": _as_text(_first(item, "expected_benefit", "benefit", "expected_result")),
        "risks": [_as_text(x) for x in _as_list(item.get("risks", []))],
        "assumptions": [_as_text(x) for x in _as_list(item.get("assumptions", []))],
        "requires_human_review": bool(_first(item, "requires_human_review", "human_review_required", default=True)),
        "source": "COORDINATOR",
        "raw": item,
    }


def normalize_coordinator_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert raw Coordinator output into Reporting Agent's canonical input."""
    if not isinstance(payload, dict):
        raise InputValidationError("Coordinator output phải là một JSON object.")

    root = _unwrap(payload)
    consistency = _first(root, "consistency_result", "consistency", "consistency_check_result", "consistency_check", default={})
    if not isinstance(consistency, dict):
        consistency = {}

    raw_findings = _find_collection(
        root,
        ("findings", "issues", "unified_findings", "consistency_findings"),
        ("findings", "issues", "items", "records"),
    )
    if not raw_findings and consistency:
        raw_findings = _find_collection(
            consistency,
            ("findings", "issues", "unified_findings"),
            ("findings", "issues", "items", "records"),
        )

    raw_recommendations = _find_collection(
        root,
        ("recommendations", "recommendation_list", "remediation_recommendations"),
        ("recommendations", "items", "results"),
    )
    if not raw_recommendations:
        raw_recommendations = _find_collection(
            root,
            ("recommendation_result", "recommendation_output"),
            ("recommendations", "items", "results"),
        )

    findings = [_normalize_finding(item, i) for i, item in enumerate(raw_findings, 1)]
    recommendations = [_normalize_recommendation(item, i) for i, item in enumerate(raw_recommendations, 1)]

    metadata_raw = _first(root, "metadata", "run_metadata", default={})
    if not isinstance(metadata_raw, dict):
        metadata_raw = {"metadata_value": _as_text(metadata_raw)}
    # Filter metadata to JSON-serializable values so report generation never fails on opaque objects.
    try:
        metadata_safe = json.loads(json.dumps(metadata_raw, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        metadata_safe = {}

    try:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        input_hash = hashlib.sha256(canonical).hexdigest()
    except (TypeError, ValueError):
        input_hash = "unavailable"

    project_id = _as_text(_first(root, "project_id", "system_id", default=metadata_raw.get("project_id")), "UNKNOWN")
    run_id = _as_text(_first(root, "run_id", "execution_id", "analysis_id", default=metadata_raw.get("run_id")), "UNKNOWN")
    project_name = _as_text(_first(root, "project_name", "system_name", "project", default="Software Project"))
    coordinator_status = _as_text(_first(root, "status", "overall_status", "coordinator_status", default="RECEIVED")).upper()
    summary = _as_text(_first(root, "summary", "coordinator_summary", "executive_summary", "message"), "Coordinator đã chuyển dữ liệu phân tích cho Reporting Agent.")
    unresolved = [_as_text(x) for x in _as_list(_first(root, "unresolved_items", "open_items", "pending_items", default=consistency.get("unresolved_items", []))) if _as_text(x)]

    warnings: list[str] = []
    if not findings:
        warnings.append("Coordinator không cung cấp finding nào; báo cáo chỉ phản ánh metadata và trạng thái nhận được.")
    if coordinator_status in {"FAILED", "ERROR"}:
        warnings.append("Coordinator báo trạng thái lỗi; không nên xem đây là kết quả phân tích hoàn chỉnh.")
    if coordinator_status in {"PARTIAL", "PARTIAL_SUCCESS", "INCOMPLETE"}:
        warnings.append("Coordinator đánh dấu kết quả chưa đầy đủ; cần đọc các unresolved items trước khi kết luận.")

    return {
        "project_id": project_id,
        "run_id": run_id,
        "project_name": project_name,
        "coordinator_status": coordinator_status,
        "coordinator_summary": summary,
        "findings": findings,
        "recommendations": recommendations,
        "unresolved_items": unresolved,
        "metadata": metadata_safe,
        "input_sha256": input_hash,
        "normalization_warnings": warnings,
    }
