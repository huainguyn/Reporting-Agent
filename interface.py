"""FastAPI interface for the independent Reporting Agent."""
from __future__ import annotations
from typing import Any
from fastapi import FastAPI, HTTPException
from reporting_agent import ReportingAgent

app = FastAPI(
    title="Reporting Agent API",
    description="Nhận output của Coordinator Agent, tổng hợp findings, liên kết recommendations và xuất báo cáo.",
    version="1.0.0",
)
agent = ReportingAgent()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "ReportingAgent", "version": "1.0.0"}


@app.post("/report")
def create_report(payload: dict[str, Any]) -> dict[str, Any]:
    result = agent.run(payload)
    if result.get("status") != "SUCCESS":
        raise HTTPException(status_code=422, detail=result)
    return result


@app.post("/report/save")
def create_and_save_report(payload: dict[str, Any]) -> dict[str, Any]:
    result = agent.run(payload)
    if result.get("status") != "SUCCESS":
        raise HTTPException(status_code=422, detail=result)
    paths = agent.save_artifacts(result, "reports/api")
    return {"status": "SUCCESS", "assessment": result["overall_assessment"], "artifacts": paths}
