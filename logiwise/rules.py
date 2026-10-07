"""결정론적 규칙 계층. 대시보드 색상, 병목 판단, 이상 센터 탐지가 모두 여기서 나옵니다.

LLM은 이 결과를 입력으로만 받습니다. 등급·병목 판정은 LLM이 바꾸지 않습니다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from . import db
from .settings import RULES, now, now_iso


def center_status(row: dict) -> str:
    """정상 / 주의 / 위험 / 데이터 없음. 미처리 이벤트는 현재 기준, 정시출고율은 최신 일별 KPI 기준."""
    rate = row.get("on_time_rate")
    if rate is None:
        return "데이터 없음"
    if rate < RULES["danger_on_time"] or row["open_anomaly_count"] >= RULES["danger_anomaly_count"]:
        return "위험"
    if rate < RULES["on_time_target"] or row["open_event_count"] > 0:
        return "주의"
    return "정상"


def bottlenecks(row: dict) -> dict[str, bool]:
    """PRD 4.2.3 병목 기준. 피킹·패킹은 PRD에 기준이 없어 항상 False."""
    return {
        "입고": row["open_missing_inbound_qty"] > RULES["inbound_bottleneck_qty"],
        "보관": row["open_anomaly_count"] > 0,
        "피킹": False,
        "패킹": False,
        "출고": row["open_unpaid_qty"] > RULES["outbound_bottleneck_qty"],
    }


def heatmap_level(count: int) -> str:
    if count >= RULES["heatmap_danger_min"]:
        return "적"
    if count >= RULES["heatmap_warn_min"]:
        return "노"
    return "녹"


def event_delay_level(due_at: str) -> str:
    """기한 이내 녹 / 24시간 미만 지연 노 / 24시간 이상 지연 적."""
    delay_hours = (now() - datetime.fromisoformat(due_at)).total_seconds() / 3600
    if delay_hours >= RULES["event_delay_danger_hours"]:
        return "적"
    if delay_hours > RULES["event_delay_warn_hours"]:
        return "노"
    return "녹"


def reasons_for(row: dict) -> list[str]:
    out = []
    if row.get("on_time_rate") is not None and row["on_time_rate"] < RULES["on_time_target"]:
        out.append(f"정시출고율 {row['on_time_rate']:.1f}% < 목표 {RULES['on_time_target']:g}%")
    for stage, blocked in bottlenecks(row).items():
        if blocked:
            value = {"입고": row["open_missing_inbound_qty"], "보관": row["open_anomaly_count"], "출고": row["open_unpaid_qty"]}[stage]
            unit = "건" if stage == "보관" else "개"
            out.append(f"{stage} 병목 (미처리 {value}{unit})")
    if row["open_event_count"]:
        out.append(f"미처리 이벤트 {row['open_event_count']}건")
    if row["overdue_event_count"]:
        out.append(f"기한 초과 이벤트 {row['overdue_event_count']}건")
    if row["open_instruction_count"]:
        out.append(f"미완료 본사 지시 {row['open_instruction_count']}건")
    return out


def snapshot(center_code: str | None = None, path=None) -> dict:
    """에이전트 도구와 화면이 공유하는 현재 상태. 모든 센터 행에 evidence_id가 붙습니다."""
    rows = db.overview(center_code, path)
    for row in rows:
        row["status"] = center_status(row)
        row["bottlenecks"] = [s for s, b in bottlenecks(row).items() if b]
        row["reasons"] = reasons_for(row)
        row["evidence_id"] = f"KPI:{row['center_code']}:{row['day']}" if row.get("day") else f"CENTER:{row['center_code']}"
    return {
        "captured_at": now_iso(),
        "kpi_day": db.latest_kpi_day(path),
        "data_kind": "교육용 샘플 데이터",
        "rules": RULES,
        "centers": rows,
        "note": "정시출고율은 일별 KPI 스냅샷. 미처리 수량·이상 건수는 현재 시점 기준. 원인은 현장 확인 필요.",
    }


def fingerprint(row: dict, open_event_ids: list[int]) -> str:
    """같은 센터가 같은 이상 상태면 같은 지문. 이벤트가 처리되거나 등급이 바뀌면 지문이 바뀝니다."""
    payload = {"center": row["center_code"], "status": row["status"], "bottlenecks": row["bottlenecks"],
               "events": sorted(open_event_ids)}
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def detect_anomalies(path=None) -> list[dict]:
    """주의·위험 센터 목록. 위험 → 주의, 정시출고율 낮은 순으로 정렬."""
    snap = snapshot(None, path)
    found = []
    for row in snap["centers"]:
        if row["status"] not in ("주의", "위험"):
            continue
        event_ids = [e["id"] for e in db.events(row["center_code"], path=path)]
        found.append({**row, "open_event_ids": event_ids, "fingerprint": fingerprint(row, event_ids)})
    rank = {"위험": 0, "주의": 1}
    found.sort(key=lambda r: (rank[r["status"]], r["on_time_rate"] if r["on_time_rate"] is not None else 101))
    return found


def rule_report(center_code: str | None = None, path=None) -> tuple[dict, list]:
    """LLM 없이 만드는 보수적 진단. 에이전트를 쓸 수 없을 때의 대체 경로이며 AI 결과로 표시하지 않습니다."""
    snap = snapshot(center_code, path)
    findings, drafts = [], []
    for row in snap["centers"]:
        if row["status"] in ("정상", "데이터 없음"):
            continue
        observation = (f"정시출고율 {row['on_time_rate']:.1f}% (목표 {RULES['on_time_target']:g}%), "
                       f"미납 {row['open_unpaid_qty']}개, 미입고 {row['open_missing_inbound_qty']}개, "
                       f"상태이상 {row['open_anomaly_count']}건, 기한초과 {row['overdue_event_count']}건")
        stages = ", ".join(row["bottlenecks"]) or "정시출고율"
        recommendation = f"{stages} 관련 미처리 이벤트를 확인하고 담당자·완료 예정 시각을 정해 조치 결과를 보고하세요."
        findings.append({"center_code": row["center_code"], "severity": row["status"], "observation": observation,
                         "hypothesis": "수치만으로 원인을 확정할 수 없습니다. 현장 확인이 필요합니다.",
                         "recommendation": recommendation, "evidence_ids": [row["evidence_id"]]})
        drafts.append({"center_code": row["center_code"], "title": f"{row['name']} {stages} 확인 및 조치 요청",
                       "body": f"관측: {observation}\n요청: {recommendation}\n보고: 조치 내용, 처리 수량, 잔여 수량, 완료 예정 시각.",
                       "priority": "긴급" if row["status"] == "위험" else "높음",
                       "evidence_ids": [row["evidence_id"]]})
    report = {"summary": f"{snap['kpi_day']} KPI·현재 미처리 이벤트 기준 {len(snap['centers'])}개 센터 중 {len(findings)}개 센터 확인 필요 (규칙 기반, 샘플 데이터).",
              "findings": findings, "instruction_drafts": drafts}
    return report, [{"tool": "snapshot", "data": snap}]
