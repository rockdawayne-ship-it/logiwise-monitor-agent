import pytest

from logiwise import db
from logiwise.db import WorkflowError


def test_full_workflow_transitions(db_path):
    iid = db.send_instruction("C001", "테스트 지시", "내용", "보통", path=db_path)
    assert db.one("SELECT status FROM WF_INSTRUCTION WHERE id=?", (iid,), db_path)["status"] == "지시완료"
    with pytest.raises(WorkflowError):
        db.submit_report(iid, "아직 확인 안 함", 1, 0, path=db_path)
    db.acknowledge_instruction(iid, path=db_path)
    with pytest.raises(WorkflowError):
        db.acknowledge_instruction(iid, path=db_path)
    db.submit_report(iid, "재출고 완료", 5, 0, path=db_path)
    assert db.one("SELECT status FROM WF_INSTRUCTION WHERE id=?", (iid,), db_path)["status"] == "조치중"
    db.approve_report(iid, path=db_path)
    assert db.one("SELECT status FROM WF_INSTRUCTION WHERE id=?", (iid,), db_path)["status"] == "완료"
    with pytest.raises(WorkflowError):
        db.approve_report(iid, path=db_path)


def test_send_instruction_validates(db_path):
    with pytest.raises(WorkflowError):
        db.send_instruction("C001", "", "x", path=db_path)
    with pytest.raises(WorkflowError):
        db.send_instruction("C099", "t", "x", path=db_path)
    with pytest.raises(WorkflowError):
        db.send_instruction("C001", "t", "x", "최고", path=db_path)


def test_resolve_event_partial_and_over(db_path):
    event = next(e for e in db.events("C003", path=db_path) if e["event_type"] == "미납" and e["remaining_qty"] >= 2)
    db.resolve_event(event["id"], "재출고", 1, path=db_path)
    after = db.one("SELECT * FROM EXC_CENTER_EVENT WHERE id=?", (event["id"],), db_path)
    assert after["status"] == "미처리" and after["remaining_qty"] == event["remaining_qty"] - 1
    with pytest.raises(WorkflowError):
        db.resolve_event(event["id"], "재출고", 999, path=db_path)
    db.resolve_event(event["id"], "대체출고", after["remaining_qty"], path=db_path)
    assert db.one("SELECT status FROM EXC_CENTER_EVENT WHERE id=?", (event["id"],), db_path)["status"] == "처리완료"
    with pytest.raises(WorkflowError):
        db.resolve_event(event["id"], "재출고", 1, path=db_path)


def test_resolve_event_rejects_unknown_type(db_path):
    event = db.events("C003", path=db_path)[0]
    with pytest.raises(WorkflowError):
        db.resolve_event(event["id"], "마법", 1, path=db_path)


def test_draft_approval_creates_instruction_once(db_path):
    run_id = db.start_run("manual", "C003", "rules", path=db_path)
    did = db.add_draft(run_id, "C003", "초안 제목", "초안 내용", "긴급", ["KPI:C003:x"], "fp1", path=db_path)
    assert "fp1" in db.pending_fingerprints(db_path)
    iid = db.approve_draft(did, title="수정된 제목", memo="확인함", path=db_path)
    inst = db.one("SELECT * FROM WF_INSTRUCTION WHERE id=?", (iid,), db_path)
    assert inst["title"] == "수정된 제목" and inst["source"] == "에이전트초안" and inst["draft_id"] == did
    assert db.one("SELECT status, instruction_id FROM WF_DRAFT WHERE id=?", (did,), db_path)["instruction_id"] == iid
    assert "fp1" not in db.pending_fingerprints(db_path)
    with pytest.raises(WorkflowError):
        db.approve_draft(did, path=db_path)
    with pytest.raises(WorkflowError):
        db.reject_draft(did, path=db_path)


def test_draft_reject(db_path):
    run_id = db.start_run("manual", "ALL", "rules", path=db_path)
    did = db.add_draft(run_id, "C005", "t", "b", "높음", [], "fp2", path=db_path)
    db.reject_draft(did, "불필요", path=db_path)
    row = db.one("SELECT status, decision_memo FROM WF_DRAFT WHERE id=?", (did,), db_path)
    assert row["status"] == "반려" and row["decision_memo"] == "불필요"
    assert db.one("SELECT COUNT(*) AS n FROM WF_INSTRUCTION WHERE draft_id=?", (did,), db_path)["n"] == 0
