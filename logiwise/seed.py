"""교육용 샘플 데이터. 실행일 기준 최근 7일을 생성합니다. 이미 데이터가 있으면 건너뜁니다."""
from __future__ import annotations

import random
from datetime import timedelta

from . import db
from .settings import now, now_iso, today

CENTERS = [
    ("C001", "서울센터", "수도권", "김서울"),
    ("C002", "이천센터", "수도권", "이이천"),
    ("C003", "대전센터", "충청", "박대전"),
    ("C004", "광주센터", "호남", "최광주"),
    ("C005", "대구센터", "영남", "정대구"),
    ("C006", "부산센터", "영남", "강부산"),
    ("C007", "제주센터", "제주", "한제주"),
]
VENDORS = [("V00001", "한빛식품"), ("V00002", "대한생활"), ("V00003", "그린케어"), ("V00004", "코어전자")]
PRODUCT_NAMES = ["생수 2L", "라면 5입", "세제 3L", "휴지 30롤", "샴푸 500ml", "치약 3입", "건전지 AA", "USB 케이블",
                 "보조배터리", "마스크 50매", "커피믹스 100T", "참치캔 6입", "식용유 1.8L", "설탕 1kg", "소금 500g",
                 "비누 4입", "물티슈 10팩", "키친타월 4롤", "쓰레기봉투 20L", "LED 전구"]
CODES = {
    "EVENT_TYPE": ["미납", "미입고", "상태이상"],
    "ANOMALY_TYPE": ["파손", "유통기한임박", "라벨오류", "온도이탈"],
    "RESOLVE_TYPE": ["재출고", "대체출고", "입고확인", "폐기", "재검수", "거래처회신"],
    "STAGE": ["입고", "보관", "피킹", "패킹", "출고"],
}
# 센터별 성격: (정시출고율 기준, 미납 기준, 미입고 기준, 상태이상 기준). C003은 위험, C005·C006은 주의로 설계.
PROFILE = {
    "C001": (98.5, 0, 0, 0), "C002": (97.8, 2, 1, 0), "C003": (93.2, 9, 5, 5), "C004": (97.4, 1, 0, 1),
    "C005": (96.1, 7, 2, 0), "C006": (95.6, 3, 4, 2), "C007": (98.0, 0, 0, 0),
}


def seed(path=None, force: bool = False) -> bool:
    db.init_schema(path)
    if not force and db.one("SELECT 1 AS x FROM MT_CENTER LIMIT 1", path=path):
        return False
    rng = random.Random(20261007)
    with db.connect(path) as conn:
        for table in ("WF_DRAFT", "MON_ALERT", "AGENT_RUN", "WF_ACTION_REPORT", "WF_INSTRUCTION",
                      "EXC_CENTER_EVENT_RESOLVE", "EXC_CENTER_EVENT", "AN_CENTER_KPI_DAILY",
                      "INV_CENTER_INOUT_DAILY", "INV_CENTER_INOUT_HISTORY", "INV_CENTER_STOCK",
                      "MT_PRODUCT", "MT_VENDOR", "MT_ETC_CODE", "MT_CENTER"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO MT_CENTER VALUES(?,?,?,?)", CENTERS)
        conn.executemany("INSERT INTO MT_VENDOR VALUES(?,?)", VENDORS)
        products = [(str(i + 1).zfill(10), name, VENDORS[i % len(VENDORS)][0]) for i, name in enumerate(PRODUCT_NAMES)]
        conn.executemany("INSERT INTO MT_PRODUCT VALUES(?,?,?)", products)
        for group, names in CODES.items():
            conn.executemany("INSERT INTO MT_ETC_CODE VALUES(?,?,?,?)",
                             [(group, name, name, i) for i, name in enumerate(names)])
        stamp = now_iso()
        for code, *_ in CENTERS:
            for pcode, _, _ in products:
                conn.execute("INSERT INTO INV_CENTER_STOCK VALUES(?,?,?,?)", (code, pcode, rng.randint(40, 400), stamp))
        days = [(today() - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]
        for code, *_ in CENTERS:
            base_rate, unpaid, missing, anomaly = PROFILE[code]
            for i, day in enumerate(days):
                drift = (i - 3) * (0.35 if code == "C003" else 0.1)
                rate = round(min(99.9, max(85.0, base_rate - drift + rng.uniform(-0.6, 0.6))), 1)
                conn.execute("INSERT INTO AN_CENTER_KPI_DAILY VALUES(?,?,?,?,?,?)",
                             (code, day, rate, max(0, unpaid + rng.randint(-1, 1)) if unpaid else 0,
                              max(0, missing + rng.randint(-1, 1)) if missing else 0,
                              max(0, anomaly + rng.randint(-1, 1)) if anomaly else 0))
                inbound = rng.randint(180, 320)
                outbound = rng.randint(170, 310)
                bottleneck = 0.75 if (code == "C003" and i >= 4) else 1.0
                conn.execute("INSERT INTO INV_CENTER_INOUT_DAILY VALUES(?,?,?,?,?,?,?)",
                             (code, day, inbound, inbound - rng.randint(0, 10), int(outbound * bottleneck),
                              int(outbound * bottleneck) - rng.randint(0, 8), int(outbound * bottleneck) - rng.randint(5, 15)))
                for stage, qty in (("입고", inbound), ("출고", int(outbound * bottleneck))):
                    conn.execute("INSERT INTO INV_CENTER_INOUT_HISTORY(center_code,product_code,stage,qty,occurred_at) VALUES(?,?,?,?,?)",
                                 (code, products[rng.randrange(len(products))][0], stage, qty, f"{day}T17:00:00+09:00"))
        # 미처리 이벤트: 프로필의 현재 수치와 일치하도록 생성
        for code, *_ in CENTERS:
            _, unpaid, missing, anomaly = PROFILE[code]
            specs = []
            if unpaid:
                specs += [("미납", None, unpaid - unpaid // 2), ("미납", None, unpaid // 2)] if unpaid > 1 else [("미납", None, unpaid)]
            if missing:
                specs.append(("미입고", None, missing))
            specs += [("상태이상", CODES["ANOMALY_TYPE"][k % 4], 1) for k in range(anomaly)]
            for k, (etype, atype, qty) in enumerate(s for s in specs if s[2] > 0):
                hours = {"C003": -30, "C005": -6, "C006": 2}.get(code, 20) + k * 3
                due = (now() + timedelta(hours=hours)).isoformat(timespec="seconds")
                conn.execute(
                    """INSERT INTO EXC_CENTER_EVENT(center_code,product_code,event_type,anomaly_type,qty,remaining_qty,due_at,status,memo,created_at)
                       VALUES(?,?,?,?,?,?,?,'미처리',?,?)""",
                    (code, products[(k * 3) % len(products)][0], etype, atype, qty, qty, due,
                     "거래처 납기 지연 추정" if etype == "미입고" else None,
                     (now() - timedelta(hours=36 - k)).isoformat(timespec="seconds")))
        conn.execute(
            "INSERT INTO WF_INSTRUCTION(center_code,title,body,priority,status,source,created_at) VALUES(?,?,?,?,?,?,?)",
            ("C003", "대전센터 출고 지연 원인 보고", "최근 3일 정시출고율 하락 원인과 미납 처리 계획을 보고해 주세요.", "높음", "지시완료", "본사",
             (now() - timedelta(days=1)).isoformat(timespec="seconds")))
        conn.execute(
            "INSERT INTO WF_INSTRUCTION(center_code,title,body,priority,status,source,created_at,checked_at) VALUES(?,?,?,?,?,?,?,?)",
            ("C005", "대구센터 미납 7개 처리 요청", "미납 수량을 48시간 내 재출고하고 결과를 보고해 주세요.", "보통", "센터확인중", "본사",
             (now() - timedelta(days=2)).isoformat(timespec="seconds"), (now() - timedelta(days=1)).isoformat(timespec="seconds")))
    return True


if __name__ == "__main__":
    import sys
    created = seed(force="--force" in sys.argv)
    print("샘플 데이터 생성 완료" if created else "기존 데이터가 있어 건너뜀 (--force 로 재생성)")
