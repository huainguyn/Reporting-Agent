from reporting_agent import ReportingAgent


def test_markdown_contains_limitations_and_csv_columns():
    result = ReportingAgent().run({
        "project_id": "p", "run_id": "r",
        "findings": [{"id": "F-1", "status": "VIOLATION", "source": "A", "target": "B"}],
    })
    assert "không tự quét mã nguồn" in result["report_markdown"]
    assert "finding_id" in result["findings_csv"]
    assert "recommendation_id" in result["recommendations_csv"]
    assert "F-1" in result["graph_mermaid"]


def test_csv_escapes_values_that_look_like_spreadsheet_formulas():
    result = ReportingAgent().run({
        "findings": [{"id": "F-1", "status": "VIOLATION", "description": "=HYPERLINK('bad')"}],
    })
    assert "'=HYPERLINK" in result["findings_csv"]
