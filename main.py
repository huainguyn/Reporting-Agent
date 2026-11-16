"""Run Reporting Agent with a sample Coordinator Agent output."""
import json
from pathlib import Path
from reporting_agent import ReportingAgent

BASE = Path(__file__).resolve().parent
payload = json.loads((BASE / "data" / "sample_coordinator_output.json").read_text(encoding="utf-8"))
agent = ReportingAgent()
result = agent.run(payload)
print(json.dumps(result, ensure_ascii=False, indent=2))
if result.get("status") == "SUCCESS":
    paths = agent.save_artifacts(result, BASE / "reports")
    print("\nĐã tạo báo cáo:")
    for kind, path in paths.items():
        print(f"- {kind}: {path}")
else:
    raise SystemExit(result.get("error", "Reporting Agent failed"))
