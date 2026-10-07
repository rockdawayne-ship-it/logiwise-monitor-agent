"""DB 연결·조회·업무 트랜잭션. 모든 쓰기는 이 모듈의 함수를 통해서만 수행합니다."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .settings import DB_PATH, DRAFT_STATUSES, WORKFLOW_STATUSES, normalize_code, now_iso

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class WorkflowError(ValueError):
    """잘못된 상태 전환 또는 입력."""


@contextmanager
def connect(path: str | Path | None = None):
    target = Path(path) if path else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(path=None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def rows(sql: str, params=(), path=None) -> list[dict]:
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql: str, params=(), path=None) -> dict | None:
    result = rows(sql, params, path)
    return result[0] if result else None


# ───────── 조회 ─────────
def centers(path=None) -> list[dict]:
    return rows("SELECT * FROM MT_CENTER ORDER BY center_code", path=path)


def latest_kpi_day(path=None) -> str | None:
    row = one("SELECT MAX(day) AS day FROM AN_CENTER_KPI_DAILY", path=path)
    return row["day"] if row else None


def overview(center_code: str | None = None, path=None) -> list[dict]:
    """센터별 최신 KPI + 현재 미처리 이벤트 집계. 대시보드와 에이전트 도구가 공유합니다."""
    sql = """
    WITH latest AS (SELECT center_code, MAX(day) AS day FROM AN_CENTER_KPI_DAILY GROUP BY center_code),
    open_ev AS (
        SELECT center_code,
               SUM(CASE WHEN event_type='미납' THEN remaining_qty ELSE 0 END)   AS open_unpaid_qty,
               SUM(CASE WHEN event_type='미입고' THEN remaining_qty ELSE 0 END) AS open_missing_inbound_qty,
               SUM(CASE WHEN event_type='상태이상' THEN 1 ELSE 0 END)           AS open_anomaly_count,
               COUNT(*) AS open_event_count,
               SUM(CASE WHEN due_at < ? THEN 1 ELSE 0 END) AS overdue_event_count
        FROM EXC_CENTER_EVENT WHERE status='미처리' GROUP BY center_code),
    stock AS (SELECT center_code, SUM(qty) AS stock_qty, COUNT(*) AS sku_count FROM INV_CENTER_STOCK GROUP BY center_code),
    wf AS (SELECT center_code, SUM(CASE WHEN status!='완료' THEN 1 ELSE 0 END) AS open_instruction_count FROM WF_INSTRUCTION GROUP BY center_code)
    SELECT c.center_code, c.name, c.region, c.manager, k.day,
           k.on_time_rate, k.unpaid_qty, k.missing_inbound_qty, k.anomaly_count,
           COALESCE(e.open_unpaid_qty,0) AS open_unpaid_qty,
           COALESCE(e.open_missing_inbound_qty,0) AS open_missing_inbound_qty,
           COALESCE(e.open_anomaly_count,0) AS open_anomaly_count,
           COALESCE(e.open_event_count,0) AS open_event_count,
           COALESCE(e.overdue_event_count,0) AS overdue_event_count,
           COALESCE(s.stock_qty,0) AS stock_qty, COALESCE(s.sku_count,0) AS sku_count,
           COALESCE(w.open_instruction_count,0) AS open_instruction_count
    FROM MT_CENTER c
    LEFT JOIN latest l ON l.center_code=c.center_code
    LEFT JOIN AN_CENTER_KPI_DAILY k ON k.center_code=l.center_code AND k.day=l.day
    LEFT JOIN open_ev e ON e.center_code=c.center_code
    LEFT JOIN stock s ON s.center_code=c.center_code
    LEFT JOIN wf w ON w.center_code=c.center_code
    """
    params: list = [now_iso()]
    if center_code:
        sql += " WHERE c.center_code=?"
        params.append(center_code)
    return rows(sql + " ORDER BY c.center_code", params, path)


def kpi_trend(center_code: str | None = None, days: int = 7, path=None) -> list[dict]:
    sql = "SELECT k.*, c.name FROM AN_CENTER_KPI_DAILY k JOIN MT_CENTER c USING(center_code)"
    params: list = []
    if center_code:
        sql += " WHERE k.center_code=?"
        params.append(center_code)
    sql += " ORDER BY k.day DESC, k.center_code LIMIT ?"
    params.append(days * (1 if center_code else 50))
    result = rows(sql, params, path)
    return sorted(result, key=lambda r: (r["day"], r["center_code"]))


def inout_daily(center_code: str, days: int = 7, path=None) -> list[dict]:
    return rows("SELECT * FROM INV_CENTER_INOUT_DAILY WHERE center_code=? ORDER BY day DESC LIMIT ?",
                (center_code, days), path)[::-1]


def events(center_code: str | None = None, status: str | None = "미처리", path=None) -> list[dict]:
    sql = """SELECT e.*, p.name AS product_name, c.name AS center_name
             FROM EXC_CENTER_EVENT e LEFT JOIN MT_PRODUCT p USING(product_code) JOIN MT_CENTER c USING(center_code)
             WHERE 1=1"""
    params: list = []
    if center_code:
        sql += " AND e.center_code=?"
        params.append(center_code)
    if status:
        sql += " AND e.status=?"
        params.append(status)
    return rows(sql + " ORDER BY e.due_at, e.id", params, path)


def instructions(center_code: str | None = None, path=None) -> list[dict]:
    sql = "SELECT i.*, c.name AS center_name FROM WF_INSTRUCTION i JOIN MT_CENTER c USING(center_code)"
    params: list = []
    if center_code:
        sql += " WHERE i.center_code=?"
        params.append(center_code)
    return rows(sql + " ORDER BY i.id DESC", params, path)


def reports(instruction_id: int, path=None) -> list[dict]:
    return rows("SELECT * FROM WF_ACTION_REPORT WHERE instruction_id=? ORDER BY id", (instruction_id,), path)


def codes(group: str, path=None) -> list[dict]:
    return rows("SELECT code, name FROM MT_ETC_CODE WHERE code_group=? ORDER BY sort_order", (group,), path)


def drafts(status: str | None = "대기", center_code: str | None = None, path=None) -> list[dict]:
    sql = "SELECT d.*, c.name AS center_name FROM WF_DRAFT d JOIN MT_CENTER c USING(center_code) WHERE 1=1"
    params: list = []
    if status:
        sql += " AND d.status=?"
        params.append(status)
    if center_code:
        sql += " AND d.center_code=?"
        params.append(center_code)
    return rows(sql + " ORDER BY d.id DESC", params, path)


def runs(limit: int = 20, path=None) -> list[dict]:
    return rows("SELECT * FROM AGENT_RUN ORDER BY id DESC LIMIT ?", (limit,), path)


def run(run_id: int, path=None) -> dict | None:
    return one("SELECT * FROM AGENT_RUN WHERE id=?", (run_id,), path)


def alerts(run_id: int | None = None, limit: int = 50, path=None) -> list[dict]:
    if run_id:
        return rows("SELECT * FROM MON_ALERT WHERE run_id=? ORDER BY id", (run_id,), path)
    return rows("SELECT * FROM MON_ALERT ORDER BY id DESC LIMIT ?", (limit,), path)


# ───────── 업무 트랜잭션: 본사 ─────────
def send_instruction(center_code: str, title: str, body: str, priority: str = "보통",
                     source: str = "본사", draft_id: int | None = None, path=None) -> int:
    center_code = normalize_code(center_code, "center")
    if not title.strip() or not body.strip():
        raise WorkflowError("지시 제목과 내용을 입력하세요.")
    if priority not in ("보통", "높음", "긴급"):
        raise WorkflowError("우선순위는 보통/높음/긴급 중 하나입니다.")
    with connect(path) as conn:
        if conn.execute("SELECT 1 FROM MT_CENTER WHERE center_code=?", (center_code,)).fetchone() is None:
            raise WorkflowError("존재하지 않는 센터입니다.")
        cur = conn.execute(
            "INSERT INTO WF_INSTRUCTION(center_code,title,body,priority,status,source,draft_id,created_at) VALUES(?,?,?,?,'지시완료',?,?,?)",
            (center_code, title.strip(), body.strip(), priority, source, draft_id, now_iso()))
        return cur.lastrowid


def approve_report(instruction_id: int, path=None) -> None:
    _transition(instruction_id, "조치중", "완료", "approved_at", path)


# ───────── 업무 트랜잭션: 센터 ─────────
def acknowledge_instruction(instruction_id: int, path=None) -> None:
    _transition(instruction_id, "지시완료", "센터확인중", "checked_at", path)


def submit_report(instruction_id: int, action_summary: str, handled_qty: int, remaining_qty: int, path=None) -> int:
    if not action_summary.strip():
        raise WorkflowError("조치 내용을 입력하세요.")
    if handled_qty < 0 or remaining_qty < 0:
        raise WorkflowError("수량은 0 이상이어야 합니다.")
    with connect(path) as conn:
        row = conn.execute("SELECT status FROM WF_INSTRUCTION WHERE id=?", (instruction_id,)).fetchone()
        if row is None:
            raise WorkflowError("지시를 찾을 수 없습니다.")
        if row["status"] not in ("센터확인중", "조치중"):
            raise WorkflowError(f"현재 상태({row['status']})에서는 보고할 수 없습니다. 먼저 확인 버튼을 누르세요.")
        cur = conn.execute(
            "INSERT INTO WF_ACTION_REPORT(instruction_id,action_summary,handled_qty,remaining_qty,reported_at) VALUES(?,?,?,?,?)",
            (instruction_id, action_summary.strip(), handled_qty, remaining_qty, now_iso()))
        conn.execute("UPDATE WF_INSTRUCTION SET status='조치중', reported_at=? WHERE id=?", (now_iso(), instruction_id))
        return cur.lastrowid


def resolve_event(event_id: int, resolve_type: str, qty: int, memo: str = "", path=None) -> int:
    if qty <= 0:
        raise WorkflowError("조치 수량은 1 이상이어야 합니다.")
    with connect(path) as conn:
        ev = conn.execute("SELECT * FROM EXC_CENTER_EVENT WHERE id=?", (event_id,)).fetchone()
        if ev is None:
            raise WorkflowError("이벤트를 찾을 수 없습니다.")
        if ev["status"] != "미처리":
            raise WorkflowError("이미 처리 완료된 이벤트입니다.")
        if conn.execute("SELECT 1 FROM MT_ETC_CODE WHERE code_group='RESOLVE_TYPE' AND code=?", (resolve_type,)).fetchone() is None:
            raise WorkflowError("조치 유형 코드가 올바르지 않습니다.")
        # 상태이상은 건 단위(qty=1)로 처리하므로 잔여 수량 개념이 없습니다.
        remaining = 0 if ev["event_type"] == "상태이상" else max(ev["remaining_qty"] - qty, 0)
        if ev["event_type"] != "상태이상" and qty > ev["remaining_qty"]:
            raise WorkflowError(f"조치 수량이 잔여 수량({ev['remaining_qty']})을 초과합니다.")
        cur = conn.execute(
            "INSERT INTO EXC_CENTER_EVENT_RESOLVE(event_id,resolve_type,qty,memo,resolved_at) VALUES(?,?,?,?,?)",
            (event_id, resolve_type, qty, memo.strip() or None, now_iso()))
        conn.execute("UPDATE EXC_CENTER_EVENT SET remaining_qty=?, status=? WHERE id=?",
                     (remaining, "처리완료" if remaining == 0 else "미처리", event_id))
        return cur.lastrowid


def _transition(instruction_id: int, expected: str, target: str, stamp_col: str, path=None) -> None:
    assert expected in WORKFLOW_STATUSES and target in WORKFLOW_STATUSES
    with connect(path) as conn:
        row = conn.execute("SELECT status FROM WF_INSTRUCTION WHERE id=?", (instruction_id,)).fetchone()
        if row is None:
            raise WorkflowError("지시를 찾을 수 없습니다.")
        if row["status"] != expected:
            raise WorkflowError(f"'{expected}' 상태에서만 '{target}'(으)로 바꿀 수 있습니다. 현재: {row['status']}")
        conn.execute(f"UPDATE WF_INSTRUCTION SET status=?, {stamp_col}=? WHERE id=?", (target, now_iso(), instruction_id))


# ───────── 에이전트 기록 ─────────
def start_run(trigger: str, scope: str, mode: str, question: str | None = None, model: str | None = None, path=None) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO AGENT_RUN(started_at,trigger,scope,mode,status,question,model) VALUES(?,?,?,?,'running',?,?)",
            (now_iso(), trigger, scope, mode, question, model))
        return cur.lastrowid


def finish_run(run_id: int, status: str, report: dict | None = None, tool_log: list | None = None,
               error: str | None = None, num_turns: int | None = None, cost_usd: float | None = None,
               duration_ms: int | None = None, session_id: str | None = None, model: str | None = None, path=None) -> None:
    with connect(path) as conn:
        conn.execute(
            """UPDATE AGENT_RUN SET finished_at=?, status=?, report_json=?, tool_log_json=?, error=?,
               num_turns=?, cost_usd=?, duration_ms=?, session_id=COALESCE(?,session_id), model=COALESCE(?,model) WHERE id=?""",
            (now_iso(), status,
             json.dumps(report, ensure_ascii=False) if report is not None else None,
             json.dumps(tool_log, ensure_ascii=False) if tool_log is not None else None,
             error, num_turns, cost_usd, duration_ms, session_id, model, run_id))


def add_alert(run_id: int, center_code: str, severity: str, reasons: list[str], fingerprint: str, path=None) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO MON_ALERT(run_id,center_code,severity,reasons,fingerprint,created_at) VALUES(?,?,?,?,?,?)",
            (run_id, center_code, severity, json.dumps(reasons, ensure_ascii=False), fingerprint, now_iso()))
        return cur.lastrowid


def pending_fingerprints(path=None) -> set[str]:
    return {r["fingerprint"] for r in rows("SELECT fingerprint FROM WF_DRAFT WHERE status='대기'", path=path)}


def add_draft(run_id: int, center_code: str, title: str, body: str, priority: str,
              evidence_ids: list[str], fingerprint: str, path=None) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO WF_DRAFT(run_id,center_code,title,body,priority,evidence_ids,fingerprint,status,created_at)
               VALUES(?,?,?,?,?,?,?,'대기',?)""",
            (run_id, center_code, title, body, priority, json.dumps(evidence_ids, ensure_ascii=False), fingerprint, now_iso()))
        return cur.lastrowid


def approve_draft(draft_id: int, title: str | None = None, body: str | None = None,
                  priority: str | None = None, memo: str = "", path=None) -> int:
    """초안 승인 = 본사 지시 발송. 승인 시 본사가 수정한 제목/내용을 우선 사용합니다."""
    with connect(path) as conn:
        d = conn.execute("SELECT * FROM WF_DRAFT WHERE id=?", (draft_id,)).fetchone()
        if d is None:
            raise WorkflowError("초안을 찾을 수 없습니다.")
        if d["status"] != "대기":
            raise WorkflowError(f"이미 {d['status']} 처리된 초안입니다.")
    instruction_id = send_instruction(d["center_code"], title or d["title"], body or d["body"],
                                      priority or d["priority"], source="에이전트초안", draft_id=draft_id, path=path)
    with connect(path) as conn:
        conn.execute("UPDATE WF_DRAFT SET status='승인', decided_at=?, decision_memo=?, instruction_id=? WHERE id=?",
                     (now_iso(), memo.strip() or None, instruction_id, draft_id))
    return instruction_id


def reject_draft(draft_id: int, memo: str = "", path=None) -> None:
    with connect(path) as conn:
        d = conn.execute("SELECT status FROM WF_DRAFT WHERE id=?", (draft_id,)).fetchone()
        if d is None:
            raise WorkflowError("초안을 찾을 수 없습니다.")
        if d["status"] != "대기":
            raise WorkflowError(f"이미 {d['status']} 처리된 초안입니다.")
        conn.execute("UPDATE WF_DRAFT SET status='반려', decided_at=?, decision_memo=? WHERE id=?",
                     (now_iso(), memo.strip() or None, draft_id))


__all__ = [name for name in dir() if not name.startswith("_")] + ["DRAFT_STATUSES"]
