"""CLI entry point for Reporting Agent."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from reporting_agent import ReportingAgent


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Generate report from Coordinator Agent JSON output.")
    parser.add_argument("--input", default=str(base / "data" / "sample_coordinator_output.json"), help="Path to Coordinator output JSON")
    parser.add_argument("--output-dir", default=str(base / "reports"), help="Folder to save generated artifacts")
    parser.add_argument("--print-json", action="store_true", help="Print full result JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"[ERROR] Không tìm thấy input file: {input_path}", file=sys.stderr)
        return 2
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[ERROR] JSON không hợp lệ tại dòng {exc.lineno}, cột {exc.colno}: {exc.msg}", file=sys.stderr)
        return 2

    agent = ReportingAgent()
    result = agent.run(payload)
    if result.get("status") != "SUCCESS":
        print("[FAILED] Reporting Agent không thể xử lý input:")
        print(result.get("error", "Unknown error"))
        return 1

    paths = agent.save_artifacts(result, args.output_dir)
    stats = result["statistics"]
    print("\n[ SUCCESS ] Reporting Agent hoàn thành")
    print(f"Project : {result['project']['project_name']} ({result['project']['project_id']})")
    print(f"Run     : {result['project']['run_id']}")
    print(f"Assess  : {result['overall_assessment']}")
    print(f"Findings: {stats['total_findings']} | Violations: {stats['findings_by_status']['VIOLATION']} | Review: {stats['findings_by_status']['REVIEW']} | Compliant: {stats['findings_by_status']['COMPLIANT']}")
    print("\nArtifacts:")
    for kind, path in paths.items():
        print(f"- {kind}: {path}")
    if result.get("warnings"):
        print("\nWarnings:")
        for warning in result["warnings"]:
            print(f"- {warning}")
    if args.print_json:
        print("\nFull result:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
