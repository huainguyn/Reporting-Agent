# Hợp đồng dữ liệu giữa Coordinator Agent và Reporting Agent

## 1. Nguyên tắc

- Input của Reporting Agent là **output cuối cùng do Coordinator Agent phát ra**.
- Coordinator chịu trách nhiệm tổng hợp các raw findings/unified findings/delta và kết quả kiểm tra nhất quán.
- Reporting Agent không đọc trực tiếp kho tri thức, không gọi lại Architecture Extraction/Code Analysis/Consistency Checking và không tự suy diễn thêm kết quả phân tích.
- Những recommendations do Coordinator cung cấp được giữ nguyên về nội dung, chỉ chuẩn hóa cấu trúc để hiển thị và liên kết.
- Nếu thiếu recommendation cho một VIOLATION, Reporting Agent chỉ phát sinh một **hướng theo dõi quy trình**, không bịa ra cách sửa kỹ thuật.

## 2. Input JSON khuyến nghị

```json
{
  "schema_version": "1.0.0",
  "project_id": "demo-ecommerce",
  "project_name": "Demo E-commerce",
  "run_id": "run-2026-001",
  "status": "COMPLETED",
  "summary": "Coordinator summary",
  "findings": [
    {
      "issue_id": "VIO-001",
      "status": "VIOLATION",
      "severity": "HIGH",
      "confidence": 0.94,
      "source_module": "UserController",
      "target_module": "UserRepository",
      "rule_id": "RULE-03",
      "rule_description": "Presentation must not access Data directly",
      "description": "A dependency violates the layer rule",
      "evidence": [
        {
          "file_path": "src/UserController.java",
          "line_start": 24,
          "line_end": 25,
          "description": "Direct repository reference"
        }
      ]
    }
  ],
  "recommendations": [
    {
      "recommendation_id": "REC-001",
      "related_finding_id": "VIO-001",
      "title": "Review dependency direction",
      "priority": "HIGH",
      "recommended_action": {
        "approach": "Coordinator-authored action",
        "steps": ["Inspect evidence", "Agree remediation plan"]
      },
      "requires_human_review": true
    }
  ],
  "unresolved_items": [],
  "metadata": {"coordinator_version": "0.1.0"}
}
```

## 3. Finding status

| Status | Ý nghĩa trong báo cáo | Disposition |
|---|---|---|
| `VIOLATION` | Coordinator kết luận có vi phạm | `REMEDIATION_REQUIRED` |
| `REVIEW` | Chưa đủ cơ sở kết luận | `HUMAN_REVIEW_REQUIRED` |
| `COMPLIANT` | Coordinator kết luận tuân thủ | `NO_ACTION_REQUIRED` |
| Khác/thiếu | Không nhận diện được trạng thái | `CLASSIFICATION_REQUIRED` |

## 4. Liên kết Recommendation–Finding

Reporting Agent ưu tiên các trường:

- `related_finding_ids`: danh sách ID findings.
- `related_finding_id`: một ID finding.
- Các alias: `related_issue_id`, `related_issue_ids`, `issue_id`, `finding_id`, `target_finding_id`.

Recommendation không có liên kết được xếp vào danh sách `unlinked_recommendations`. Recommendation tham chiếu ID không tồn tại sẽ được giữ lại và tạo warning, không tự gắn sang finding khác.

## 5. Các envelope/alias được hỗ trợ

Agent hỗ trợ một số cấu trúc thường gặp:

- Payload trực tiếp: `{ "project_id": ..., "findings": [...] }`.
- Bọc ngoài: `{ "coordinator_output": { ... } }`, `{ "result": { ... } }`, `{ "output": { ... } }`.
- Findings alias: `issues`, `unified_findings`, `consistency_findings`.
- Findings lồng trong: `consistency_result`, `consistency`, `consistency_check_result`, `consistency_check`, `analysis_result`, `aggregated_result`, `results`.
- Recommendation có thể nằm trong `recommendation_result.recommendations`.

Đây là adapter tương thích đầu vào, không thay thế việc thống nhất schema chính thức giữa các agent.

## 6. Output

`ReportingAgent.run(payload)` trả về object gồm:

- `overall_assessment`: `ATTENTION_REQUIRED`, `REVIEW_REQUIRED`, `COMPLIANT`, `NO_FINDINGS_REPORTED`, `PARTIAL_DATA`, `SOURCE_FAILED` hoặc `INSUFFICIENT_DATA`.
- `statistics`: đếm findings theo status/severity, recommendation coverage, evidence và unresolved items.
- `findings`: danh sách đã chuẩn hóa, severity mặc định nếu thiếu, recommendation IDs, disposition.
- `recommendations`: các recommendation từ Coordinator.
- `generated_guidance`: hướng theo dõi quy trình được Reporting Agent sinh theo rule, không phải technical fix.
- `warnings`: lỗi liên kết hoặc vấn đề chất lượng dữ liệu.
- `report_markdown`, `graph_mermaid`, `findings_csv`, `recommendations_csv`.

## 7. Lưu ý diễn giải

Nếu Coordinator không gửi findings, báo cáo ghi nhận “không có findings được chuyển sang”, không được diễn giải thành “hệ thống chắc chắn không có lỗi”. Severity tự gán chỉ là mặc định trình bày khi Coordinator không cung cấp; confidence không được dùng thay thế severity.
