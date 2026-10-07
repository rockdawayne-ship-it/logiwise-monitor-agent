"""에이전트 검증 로직과 모니터 사이클을 LLM 호출 없이 검증합니다."""
import json

import pytest

from logiwise import agent, db, monitor, rules
from logiwise.agent import AgentUnavailable, validate_report


def _tool_log():
    return [{"tool": "get_operating_snapshot", "data": {}}]


def test_validate_report_accepts_grounded_output():
    evidence = {"KPI:C003:2026-10-07": "C003", "EVENT:5": "C003"}
    report = {"summary": "s", "findings": [{"center_code": "C003", "severity": "위험", "observation": "o", "hypothesis": "h",
                                           "recommendation": "r", "evidence_ids": ["KPI:C003:2026-10-07", "EVENT:5"]}],
              "instruction_drafts": [{"center_code": "C003", "title": "t", "body": "b", "priority": "긴급", "evidence_ids": ["EVENT:5"]}]}
    out = validate_report(report, {"C003"}, evidence, _tool_log())
    assert out["findings"][0]["center_code"] == "C003"


@pytest.mark.parametrize("bad", [
    {"center_code": "C009", "evidence_ids": ["KPI:C003:x"]},            # 범위 밖 센터
    {"center_code": "C003", "evidence_ids": []},                         # 근거 없음
    {"center_code": "C003", "evidence_ids": ["KPI:C003:made-up"]},       # 조회 안 된 근거
    {"center_code": "C003", "evidence_ids": ["KPI:C005:x"]},             # 다른 센터 근거
])
def test_validate_report_rejects_ungrounded(bad):
    evidence = {"KPI:C003:x": "C003", "KPI:C005:x": "C005"}
    report = {"summary": "s", "findings": [{"severity": "위험", "observation": "o", "hypothesis": "h", "recommendation": "r", **bad}],
              "instruction_drafts": []}
    with pytest.raises(AgentUnavailable):
        validate_report(report, {"C003", "C005"}, evidence, _tool_log())


def test_validate_report_requires_snapshot_call_and_matching_draft():
    evidence = {"KPI:C003:x": "C003"}
    finding = {"center_code": "C003", "severity": "위험", "observation": "o", "hypothesis": "h", "recommendation": "r", "evidence_ids": ["KPI:C003:x"]}
    with pytest.raises(AgentUnavailable):
        validate_report({"summary": "s", "findings": [finding], "instruction_drafts": []}, {"C003"}, evidence, [])
    draft = {"center_code": "C005", "title": "t", "body": "b", "priority": "보통", "evidence_ids": []}
    with pytest.raises(AgentUnavailable):
        validate_report({"summary": "s", "findings": [finding], "instruction_drafts": [draft]}, {"C003", "C005"}, evidence, _tool_log())


def test_output_schema_is_json_schema_object():
    schema = agent.AgentReport.model_json_schema()
    assert schema["type"] == "object"
    assert {"summary", "findings", "instruction_drafts"} <= set(schema["required"])


def test_rules_cycle_creates_drafts_and_dedupes(db_path):
    first = monitor.run_cycle("test", use_agent=False, path=db_path)
    assert first.status == "success"
    assert first.targets[0] == "C003"
    assert len(first.draft_ids) == len(first.targets)
    assert db.run(first.run_id, db_path)["status"] == "success"
    assert len(db.alerts(first.run_id, path=db_path)) == len(first.anomalies)

    # 사이클당 최대 센터 수를 넘는 이상은 다음 사이클로 넘어간다. 모두 처리되면 skipped.
    seen = set(first.targets)
    for _ in range(5):
        nxt = monitor.run_cycle("test", use_agent=False, path=db_path)
        if nxt.status == "skipped":
            break
        assert not (set(nxt.targets) & seen)
        seen |= set(nxt.targets)
    assert nxt.status == "skipped"
    assert set(nxt.skipped_pending) == {r["center_code"] for r in first.anomalies}
    assert nxt.draft_ids == []
    assert len(db.drafts("대기", path=db_path)) == len(first.anomalies)

    # 초안을 반려하면 지문이 대기열에서 빠지므로 다음 사이클에 다시 대상이 된다
    db.reject_draft(first.draft_ids[0], "테스트", path=db_path)
    third = monitor.run_cycle("test", use_agent=False, path=db_path)
    assert third.status == "success" and "C003" in third.targets


def test_cycle_approval_flows_into_workflow(db_path):
    cycle = monitor.run_cycle("test", use_agent=False, path=db_path)
    iid = db.approve_draft(cycle.draft_ids[0], path=db_path)
    inst = db.one("SELECT * FROM WF_INSTRUCTION WHERE id=?", (iid,), db_path)
    assert inst["status"] == "지시완료" and inst["source"] == "에이전트초안"
    assert inst["center_code"] == cycle.targets[0]
    draft = db.one("SELECT evidence_ids FROM WF_DRAFT WHERE id=?", (cycle.draft_ids[0],), db_path)
    assert json.loads(draft["evidence_ids"])


def test_agent_cycle_failure_is_recorded(db_path, monkeypatch):
    def boom(question, scope, path=None):
        raise AgentUnavailable("테스트 실패")
    monkeypatch.setattr(monitor, "analyze", boom)
    result = monitor.run_cycle("test", use_agent=True, path=db_path)
    assert result.status == "failed" and result.error == "테스트 실패"
    run = db.run(result.run_id, db_path)
    assert run["status"] == "failed" and run["error"] == "테스트 실패"
    assert db.drafts("대기", path=db_path) == []


def test_build_question_lists_targets(db_path):
    found = rules.detect_anomalies(db_path)
    text = monitor.build_question(found[:2])
    assert found[0]["center_code"] in text and "초안" in text
