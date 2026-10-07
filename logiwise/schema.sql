-- LOGIWISE 스키마. PRD 7.1의 12개 테이블 + 에이전트용 3개 테이블.
PRAGMA foreign_keys = ON;

-- ───────── 마스터 ─────────
CREATE TABLE IF NOT EXISTS MT_CENTER (
    center_code TEXT PRIMARY KEY,            -- C001
    name        TEXT NOT NULL,
    region      TEXT NOT NULL,
    manager     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS MT_VENDOR (
    vendor_code TEXT PRIMARY KEY,            -- V00001
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS MT_PRODUCT (
    product_code TEXT PRIMARY KEY,           -- 0000000001
    name         TEXT NOT NULL,
    vendor_code  TEXT NOT NULL REFERENCES MT_VENDOR(vendor_code)
);

CREATE TABLE IF NOT EXISTS MT_ETC_CODE (
    code_group TEXT NOT NULL,                -- EVENT_TYPE / ANOMALY_TYPE / RESOLVE_TYPE / STAGE
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (code_group, code)
);

-- ───────── 재고 ─────────
CREATE TABLE IF NOT EXISTS INV_CENTER_STOCK (
    center_code  TEXT NOT NULL REFERENCES MT_CENTER(center_code),
    product_code TEXT NOT NULL REFERENCES MT_PRODUCT(product_code),
    qty          INTEGER NOT NULL CHECK (qty >= 0),
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (center_code, product_code)
);

CREATE TABLE IF NOT EXISTS INV_CENTER_INOUT_HISTORY (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    center_code  TEXT NOT NULL REFERENCES MT_CENTER(center_code),
    product_code TEXT NOT NULL REFERENCES MT_PRODUCT(product_code),
    stage        TEXT NOT NULL,              -- 입고/보관/피킹/패킹/출고
    qty          INTEGER NOT NULL,
    occurred_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS INV_CENTER_INOUT_DAILY (
    center_code  TEXT NOT NULL REFERENCES MT_CENTER(center_code),
    day          TEXT NOT NULL,              -- YYYY-MM-DD
    inbound_qty  INTEGER NOT NULL DEFAULT 0,
    storage_qty  INTEGER NOT NULL DEFAULT 0,
    picking_qty  INTEGER NOT NULL DEFAULT 0,
    packing_qty  INTEGER NOT NULL DEFAULT 0,
    outbound_qty INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (center_code, day)
);

-- ───────── 분석 ─────────
CREATE TABLE IF NOT EXISTS AN_CENTER_KPI_DAILY (
    center_code         TEXT NOT NULL REFERENCES MT_CENTER(center_code),
    day                 TEXT NOT NULL,
    on_time_rate        REAL NOT NULL,       -- 정시출고율 %
    unpaid_qty          INTEGER NOT NULL,    -- 미납(미출고) 수량
    missing_inbound_qty INTEGER NOT NULL,    -- 미입고 수량
    anomaly_count       INTEGER NOT NULL,    -- 상태이상 건수
    PRIMARY KEY (center_code, day)
);

-- ───────── 예외 ─────────
CREATE TABLE IF NOT EXISTS EXC_CENTER_EVENT (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    center_code   TEXT NOT NULL REFERENCES MT_CENTER(center_code),
    product_code  TEXT REFERENCES MT_PRODUCT(product_code),
    event_type    TEXT NOT NULL,             -- 미납/미입고/상태이상
    anomaly_type  TEXT,                      -- 상태이상 세부 유형
    qty           INTEGER NOT NULL DEFAULT 0,
    remaining_qty INTEGER NOT NULL DEFAULT 0,
    due_at        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT '미처리',  -- 미처리/처리완료
    memo          TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_event_center_status ON EXC_CENTER_EVENT(center_code, status);

CREATE TABLE IF NOT EXISTS EXC_CENTER_EVENT_RESOLVE (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     INTEGER NOT NULL REFERENCES EXC_CENTER_EVENT(id),
    resolve_type TEXT NOT NULL,
    qty          INTEGER NOT NULL CHECK (qty > 0),
    memo         TEXT,
    resolved_at  TEXT NOT NULL
);

-- ───────── 워크플로우 ─────────
CREATE TABLE IF NOT EXISTS WF_INSTRUCTION (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    center_code TEXT NOT NULL REFERENCES MT_CENTER(center_code),
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    priority    TEXT NOT NULL DEFAULT '보통',     -- 보통/높음/긴급
    status      TEXT NOT NULL DEFAULT '지시완료', -- 지시완료/센터확인중/조치중/완료
    source      TEXT NOT NULL DEFAULT '본사',     -- 본사 / 에이전트초안
    draft_id    INTEGER,                          -- 에이전트 초안에서 승인된 경우
    created_at  TEXT NOT NULL,
    checked_at  TEXT,
    reported_at TEXT,
    approved_at TEXT
);

CREATE TABLE IF NOT EXISTS WF_ACTION_REPORT (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    instruction_id INTEGER NOT NULL REFERENCES WF_INSTRUCTION(id),
    action_summary TEXT NOT NULL,
    handled_qty    INTEGER NOT NULL DEFAULT 0,
    remaining_qty  INTEGER NOT NULL DEFAULT 0,
    reported_at    TEXT NOT NULL
);

-- ───────── 에이전트 ─────────
-- 모니터링 사이클 1회 = AGENT_RUN 1행. 규칙 스캔만 한 사이클도 기록합니다.
CREATE TABLE IF NOT EXISTS AGENT_RUN (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    trigger       TEXT NOT NULL,             -- scheduler / manual / chat
    scope         TEXT NOT NULL,             -- ALL 또는 센터코드
    mode          TEXT NOT NULL,             -- agent / rules
    status        TEXT NOT NULL,             -- running / success / failed / skipped
    model         TEXT,
    num_turns     INTEGER,
    cost_usd      REAL,
    duration_ms   INTEGER,
    question      TEXT,
    report_json   TEXT,                      -- 구조화 출력(검증 통과본)
    tool_log_json TEXT,                      -- 도구 호출 기록 + 근거
    error         TEXT,
    session_id    TEXT
);

-- 규칙 스캐너가 사이클마다 탐지한 이상 센터. 중복 호출 방지용 지문 포함.
CREATE TABLE IF NOT EXISTS MON_ALERT (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES AGENT_RUN(id),
    center_code TEXT NOT NULL REFERENCES MT_CENTER(center_code),
    severity    TEXT NOT NULL,               -- 주의/위험
    reasons     TEXT NOT NULL,               -- JSON 배열
    fingerprint TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- 에이전트가 생성한 지시 초안 대기열. 본사가 승인해야 WF_INSTRUCTION이 됩니다.
CREATE TABLE IF NOT EXISTS WF_DRAFT (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL REFERENCES AGENT_RUN(id),
    center_code    TEXT NOT NULL REFERENCES MT_CENTER(center_code),
    title          TEXT NOT NULL,
    body           TEXT NOT NULL,
    priority       TEXT NOT NULL,
    evidence_ids   TEXT NOT NULL,            -- JSON 배열
    fingerprint    TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT '대기',  -- 대기/승인/반려
    created_at     TEXT NOT NULL,
    decided_at     TEXT,
    decision_memo  TEXT,
    instruction_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_draft_status ON WF_DRAFT(status, center_code);
