"""자율 모니터링 사이클.

규칙 스캔(결정론) → 새 이상 센터만 골라 에이전트 진단 → 지시 초안을 대기열에 적재.
본사가 승인해야 WF_INSTRUCTION(지시완료)이 됩니다. 에이전트는 어떤 업무 상태도 직접 바꾸지 않습니다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import db, rules
from .agent import AgentUnavailable, analyze
from .settings import MONITOR

log = logging.getLogger("logiwise.monitor")


@dataclass
class CycleResult:
    run_id: int
    status: str                      # success / skipped / failed
    anomalies: list[dict] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    draft_ids: list[int] = field(default_factory=list)
    report: dict | None = None
    error: str | None = None
    model: str | None = None
    cost_usd: float | None = None


def build_question(targets: list[dict]) -> str:
    lines = ["규칙 스캐너가 다음 센터에서 이상을 탐지했다. 각 센터를 상세 조회해 진단하고, 센터별로 본사 검토용 지시 초안을 1개씩 작성해라."]
    for row in targets:
        lines.append(f"- {row['center_code']} {row['name']} [{row['status']}]: " + "; ".join(row["reasons"]))
    lines.append("초안 본문에는 관측 수치, 요청 조치, 보고 항목(조치 내용·처리 수량·잔여 수량·완료 예정 시각)을 포함해라.")
    return "\n".join(lines)


def run_cycle(trigger: str = "scheduler", use_agent: bool = True, path=None) -> CycleResult:
    mode = "agent" if use_agent else "rules"
    run_id = db.start_run(trigger, "ALL", mode, path=path)
    anomalies = rules.detect_anomalies(path)
    for row in anomalies:
        db.add_alert(run_id, row["center_code"], row["status"], row["reasons"], row["fingerprint"], path)

    pending = db.pending_fingerprints(path) if MONITOR.get("dedupe", True) else set()
    skipped = [r["center_code"] for r in anomalies if r["fingerprint"] in pending]
    targets = [r for r in anomalies if r["fingerprint"] not in pending][: int(MONITOR.get("max_centers_per_cycle", 3))]
    result = CycleResult(run_id=run_id, status="skipped", anomalies=anomalies,
                         targets=[r["center_code"] for r in targets], skipped_pending=skipped)
    if not targets:
        db.finish_run(run_id, "skipped", error=None if anomalies else "이상 센터 없음", path=path)
        log.info("run %s: 이상 %d개, 신규 대상 없음 (대기 초안 %d개)", run_id, len(anomalies), len(skipped))
        return result

    question = build_question(targets)
    scope = {r["center_code"] for r in targets}
    try:
        if use_agent:
            agent_result = analyze(question, scope, path)
            report, tool_log = agent_result.report, agent_result.tool_log
            result.model, result.cost_usd = agent_result.model, agent_result.cost_usd
            meta = dict(num_turns=agent_result.num_turns, cost_usd=agent_result.cost_usd,
                        duration_ms=agent_result.duration_ms, session_id=agent_result.session_id, model=agent_result.model)
        else:
            report, tool_log = rules.rule_report(None, path)
            report["findings"] = [f for f in report["findings"] if f["center_code"] in scope]
            report["instruction_drafts"] = [d for d in report["instruction_drafts"] if d["center_code"] in scope]
            meta = {}
    except AgentUnavailable as exc:
        db.finish_run(run_id, "failed", error=str(exc), path=path)
        result.status, result.error = "failed", str(exc)
        log.warning("run %s 실패: %s", run_id, exc)
        return result

    by_code = {r["center_code"]: r for r in targets}
    for draft in report.get("instruction_drafts", []):
        row = by_code.get(draft["center_code"])
        if row is None:
            continue
        did = db.add_draft(run_id, draft["center_code"], draft["title"], draft["body"], draft["priority"],
                           draft.get("evidence_ids", []), row["fingerprint"], path)
        result.draft_ids.append(did)
    db.finish_run(run_id, "success", report, tool_log, path=path, **meta)
    result.status, result.report = "success", report
    log.info("run %s: 이상 %d개, 진단 %d개, 초안 %d개 적재", run_id, len(anomalies), len(report.get("findings", [])), len(result.draft_ids))
    return result
