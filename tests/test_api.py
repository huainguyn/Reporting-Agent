from fastapi.testclient import TestClient
from interface import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["agent"] == "ReportingAgent"


def test_report_endpoint_accepts_coordinator_payload():
    response = client.post("/report", json={
        "project_id": "api-demo", "run_id": "api-run",
        "findings": [{"id": "API-1", "status": "REVIEW", "description": "Check this"}],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["findings"][0]["finding_id"] == "API-1"


def test_report_endpoint_rejects_invalid_envelope():
    response = client.post("/report", json={"coordinator_output": "wrong type"})
    assert response.status_code == 422
