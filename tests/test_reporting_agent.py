import json
from pathlib import Path
from reporting_agent import ReportingAgent

BASE = Path(__file__).resolve().parents[1]

def sample():
    return json.loads((BASE / "data" / "sample_coordinator_output.json").read_text(encoding="utf-8"))

def test_generates_report_from_coordinator_output():
    result = ReportingAgent().run(sample())
    assert result["status"] == "SUCCESS"
    assert result["agent_name"] == "ReportingAgent"
    assert result["statistics"]["total_findings"] == 3
    assert "VIO-001" in result["report_markdown"]
    assert "flowchart TD" in result["graph_mermaid"]

def test_accepts_wrapped_coordinator_output():
    result = ReportingAgent().run({"coordinator_output": sample()})
    assert result["status"] == "SUCCESS"

def test_invalid_input_returns_failed():
    result = ReportingAgent().run({"coordinator_output": "not-an-object"})
    assert result["status"] == "FAILED"
