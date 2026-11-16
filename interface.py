"""HTTP API for the Reporting Agent. POST /report receives Coordinator output."""
from fastapi import FastAPI, HTTPException
from reporting_agent import ReportingAgent

app = FastAPI(
    title="Reporting Agent API",
    description="Nhận output từ Coordinator Agent và tạo báo cáo, Mermaid graph, JSON.",
    version="1.0.0",
)
agent = ReportingAgent()

@app.get("/health")
def health():
    return {"status": "ok", "agent": "ReportingAgent"}

@app.post("/report")
def create_report(payload: dict):
    result = agent.run(payload)
    if result.get("status") != "SUCCESS":
        raise HTTPException(status_code=422, detail=result)
    return result
