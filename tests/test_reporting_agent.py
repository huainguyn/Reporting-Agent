import json
from pathlib import Path

import pytest

from reporting_agent import ReportingAgent
from reporting_agent.normalizer import normalize_coordinator_output, InputValidationError

BASE = Path(__file__).resolve().parents[1]


def sample():
    return json.loads((BASE / "data" / "sample_coordinator_output.json").read_text(encoding="utf-8"))


def test_sample_generates_full_report_and_statistics():
    result = ReportingAgent().run(sample())
    assert result["status"] == "SUCCESS"
    assert result["agent_name"] == "ReportingAgent"
    assert result["overall_assessment"] == "ATTENTION_REQUIRED"
    assert result["statistics"]["total_findings"] == 3
    assert result["statistics"]["findings_by_status"] == {
        "VIOLATION": 1, "REVIEW": 1, "COMPLIANT": 1, "UNKNOWN": 0
    }
    assert "VIO-001" in result["report_markdown"]
    assert "REV-002" in result["report_markdown"]
    assert "CMP-003" in result["report_markdown"]
    assert "flowchart TD" in result["graph_mermaid"]
    assert "REC-VIO-001" in result["graph_mermaid"]


def test_accepts_coordinator_envelope():
    result = ReportingAgent().run({"coordinator_output": sample()})
    assert result["status"] == "SUCCESS"
    assert result["statistics"]["total_findings"] == 3


def test_accepts_result_envelope():
    result = ReportingAgent().run({"result": sample()})
    assert result["status"] == "SUCCESS"


def test_accepts_findings_nested_in_consistency_result():
    payload = {
        "project_id": "nested", "run_id": "r1",
        "consistency_result": {"findings": [{"id": "N-1", "status": "FAIL", "description": "bad"}]},
        "recommendation_result": {"recommendations": [{"id": "R-1", "related_issue_id": "N-1", "action": "review"}]}
    }
    result = ReportingAgent().run(payload)
    assert result["status"] == "SUCCESS"
    assert result["findings"][0]["status"] == "VIOLATION"
    assert result["findings"][0]["recommendation_ids"] == ["R-1"]


def test_status_alias_and_confidence_percentage_normalized():
    normalized = normalize_coordinator_output({
        "findings": [{"id": "A", "status": "PASS", "confidence": 94}],
    })
    assert normalized["findings"][0]["status"] == "COMPLIANT"
    assert normalized["findings"][0]["confidence"] == 0.94


def test_violation_without_recommendation_gets_process_guidance_not_technical_fix():
    result = ReportingAgent().run({
        "project_id": "p", "run_id": "r",
        "findings": [{"id": "V-1", "status": "VIOLATION", "description": "A violation"}]
    })
    assert result["generated_guidance"][0]["related_finding_id"] == "V-1"
    assert result["generated_guidance"][0]["is_technical_fix"] is False
    assert "không tự suy diễn" in result["findings"][0]["reporting_note"]


def test_review_gets_review_guidance_but_compliant_does_not():
    result = ReportingAgent().run({
        "findings": [
            {"id": "R-1", "status": "REVIEW"},
            {"id": "C-1", "status": "COMPLIANT"},
        ]
    })
    assert len(result["generated_guidance"]) == 1
    assert result["generated_guidance"][0]["related_finding_id"] == "R-1"


def test_recommendation_with_unknown_finding_is_not_guessed_or_silently_linked():
    result = ReportingAgent().run({
        "findings": [{"id": "F-1", "status": "VIOLATION"}],
        "recommendations": [{"id": "REC-X", "related_finding_id": "MISSING", "action": "Inspect"}],
    })
    assert result["findings"][0]["recommendation_ids"] == []
    assert result["unlinked_recommendations"][0]["recommendation_id"] == "REC-X"
    assert any("MISSING" in warning for warning in result["warnings"])


def test_recommendation_can_link_to_multiple_findings():
    result = ReportingAgent().run({
        "findings": [
            {"id": "F-1", "status": "VIOLATION"},
            {"id": "F-2", "status": "VIOLATION"},
        ],
        "recommendations": [{"id": "REC-1", "related_finding_ids": ["F-1", "F-2"]}],
    })
    assert result["findings"][0]["recommendation_ids"] == ["REC-1"]
    assert result["findings"][1]["recommendation_ids"] == ["REC-1"]
    assert result["statistics"]["violation_recommendation_coverage_percent"] == 100.0


def test_duplicate_finding_ids_raise_warning():
    result = ReportingAgent().run({
        "findings": [
            {"id": "DUP", "status": "VIOLATION"},
            {"id": "DUP", "status": "REVIEW"},
        ]
    })
    assert any("bị trùng" in warning for warning in result["warnings"])


def test_empty_findings_does_not_claim_system_is_compliant():
    result = ReportingAgent().run({"project_id": "p", "run_id": "r", "findings": []})
    assert result["overall_assessment"] == "NO_FINDINGS_REPORTED"
    assert any("không cung cấp finding" in warning for warning in result["warnings"])


def test_partial_coordinator_status_is_preserved_as_partial_assessment():
    result = ReportingAgent().run({"status": "PARTIAL", "findings": [{"id": "F", "status": "COMPLIANT"}]})
    assert result["overall_assessment"] == "PARTIAL_DATA"


def test_invalid_input_returns_failed():
    result = ReportingAgent().run({"coordinator_output": "not-an-object"})
    assert result["status"] == "FAILED"
    assert "JSON object" in result["error"]


def test_non_object_payload_raises_normalizer_error():
    with pytest.raises(InputValidationError):
        normalize_coordinator_output(["not", "object"])


def test_artifacts_are_saved(tmp_path):
    agent = ReportingAgent()
    result = agent.run(sample())
    paths = agent.save_artifacts(result, tmp_path)
    assert set(paths) == {"markdown", "mermaid", "json", "findings_csv", "recommendations_csv"}
    for path in paths.values():
        assert Path(path).is_file()
        assert Path(path).stat().st_size > 0
    saved = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert saved["project"]["project_id"] == "demo-ecommerce"


def test_confidence_out_of_range_is_not_accepted():
    normalized = normalize_coordinator_output({"findings": [{"id": "F", "status": "REVIEW", "confidence": 150}]})
    assert normalized["findings"][0]["confidence"] is None


def test_findings_without_evidence_are_counted():
    result = ReportingAgent().run({"findings": [{"id": "F", "status": "REVIEW"}]})
    assert result["statistics"]["findings_without_evidence"] == 1
    assert "không cung cấp evidence" in result["report_markdown"]
