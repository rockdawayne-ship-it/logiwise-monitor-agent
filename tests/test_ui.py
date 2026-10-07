"""Streamlit AppTest로 세 화면이 오류 없이 렌더링되고 핵심 요소가 있는지 확인합니다."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from logiwise import db, monitor

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _app(nav: str, session_db) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["nav"] = nav
    at.run()
    assert not at.exception, at.exception
    return at


def test_hq_view_renders(session_db):
    at = _app("본사 관제", session_db)
    assert at.title[0].value == "본사 관제"
    labels = [m.label for m in at.metric]
    assert "전국 총 재고량" in labels and "이상 발생 센터 수" in labels
    assert any("정시출고율" in m.label for m in at.metric)


def test_hq_shows_pending_drafts_and_approval_form(session_db):
    cycle = monitor.run_cycle("test", use_agent=False, path=session_db)
    assert cycle.draft_ids
    at = _app("본사 관제", session_db)
    pending_metric = next(m for m in at.metric if "승인 대기 초안" in m.label)
    assert str(pending_metric.value) == str(len(cycle.draft_ids))
    assert any("승인하고 지시 발송" in b.label for b in at.button)
    assert len(db.drafts("대기", path=session_db)) == len(cycle.draft_ids)


def test_center_view_renders_with_banner(session_db):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["nav"] = "센터 업무"
    at.session_state["selected_center"] = "C003"
    at.run()
    assert not at.exception, at.exception
    assert "대전센터" in at.title[0].value
    assert any("미완료 본사 지시" in w.value for w in at.warning)
    assert at.metric[0].label == "보관 SKU 수"


def test_agent_console_renders_and_rules_cycle_button_works(session_db):
    at = _app("에이전트 콘솔", session_db)
    assert at.title[0].value == "에이전트 콘솔"
    buttons = {b.label: b for b in at.button}
    rules_button = next(b for label, b in buttons.items() if "규칙 기반 사이클" in label)
    rules_button.click().run()
    assert not at.exception, at.exception
    assert db.runs(1, session_db)[0]["mode"] == "rules"
    assert at.session_state["last_cycle"]["status"] == "success"
