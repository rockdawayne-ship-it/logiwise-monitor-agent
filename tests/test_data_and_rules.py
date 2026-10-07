import pytest

from logiwise import db, rules
from logiwise.settings import normalize_code


def test_schema_has_prd_tables_plus_agent_tables(db_path):
    names = {r["name"] for r in db.rows("SELECT name FROM sqlite_master WHERE type='table'", path=db_path)}
    prd = {"MT_CENTER", "MT_VENDOR", "MT_PRODUCT", "MT_ETC_CODE", "INV_CENTER_STOCK", "INV_CENTER_INOUT_HISTORY",
           "INV_CENTER_INOUT_DAILY", "AN_CENTER_KPI_DAILY", "EXC_CENTER_EVENT", "EXC_CENTER_EVENT_RESOLVE",
           "WF_INSTRUCTION", "WF_ACTION_REPORT"}
    assert prd <= names
    assert {"AGENT_RUN", "MON_ALERT", "WF_DRAFT"} <= names


def test_seed_is_idempotent(db_path):
    from logiwise import seed
    assert seed.seed(db_path) is False
    assert len(db.centers(db_path)) == 7


def test_code_normalization():
    assert normalize_code("c1", "center") == "C001"
    assert normalize_code("12", "vendor") == "V00012"
    assert normalize_code("7", "product") == "0000000007"
    with pytest.raises(ValueError):
        normalize_code("C12345", "center")


def test_overview_matches_open_events(db_path):
    row = next(r for r in db.overview(path=db_path) if r["center_code"] == "C003")
    open_events = db.events("C003", path=db_path)
    assert row["open_event_count"] == len(open_events)
    assert row["open_unpaid_qty"] == sum(e["remaining_qty"] for e in open_events if e["event_type"] == "미납")


def test_status_and_bottlenecks_follow_prd_thresholds(db_path):
    snap = rules.snapshot(path=db_path)
    by_code = {r["center_code"]: r for r in snap["centers"]}
    assert by_code["C003"]["status"] == "위험"
    assert set(by_code["C003"]["bottlenecks"]) == {"입고", "보관", "출고"}
    assert by_code["C001"]["status"] == "정상"
    assert by_code["C005"]["status"] == "주의"
    assert by_code["C005"]["bottlenecks"] == ["출고"]  # 미납 7 > 5, 미입고 2 <= 3


def test_heatmap_levels():
    assert rules.heatmap_level(0) == "녹"
    assert rules.heatmap_level(3) == "노"
    assert rules.heatmap_level(4) == "적"


def test_detect_anomalies_sorted_and_fingerprinted(db_path):
    found = rules.detect_anomalies(db_path)
    codes = [r["center_code"] for r in found]
    assert codes[0] == "C003"
    assert "C001" not in codes
    assert all(len(r["fingerprint"]) == 16 for r in found)
    # 이벤트 하나를 처리하면 지문이 바뀐다
    target = next(r for r in found if r["center_code"] == "C006")
    event = db.events("C006", path=db_path)[0]
    db.resolve_event(event["id"], "재검수" if event["event_type"] == "상태이상" else "재출고", event["remaining_qty"] or 1, path=db_path)
    after = next(r for r in rules.detect_anomalies(db_path) if r["center_code"] == "C006")
    assert after["fingerprint"] != target["fingerprint"]


def test_rule_report_has_evidence(db_path):
    report, log = rules.rule_report(path=db_path)
    assert report["findings"]
    assert all(f["evidence_ids"] for f in report["findings"])
    assert log[0]["tool"] == "snapshot"
