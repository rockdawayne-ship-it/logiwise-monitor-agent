"""에이전트 콘솔: 모니터링 사이클 실행, 실행 이력, 대화형 질의."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from logiwise import agent, db, monitor
from logiwise.agent import AgentUnavailable
from logiwise.settings import AGENT, MONITOR

from .common import flash


def render() -> None:
    st.title("에이전트 콘솔")
    st.write("규칙 스캐너가 이상 센터를 찾으면 Claude 에이전트가 원인을 조회하고 지시 초안을 대기열에 올립니다. 발송은 본사 승인으로만 이루어집니다.")
    model_label = AGENT.get("model") or "Claude Code CLI 기본 모델"
    st.caption(f"모델 {model_label} · effort {AGENT.get('effort')} · 사이클 주기 {MONITOR.get('interval_seconds')}초 (스케줄러 별도 실행) · 인증: Claude Code 로그인")

    tab_run, tab_history, tab_chat = st.tabs(["모니터링 실행", "실행 이력", "운영 질의"])

    with tab_run:
        c1, c2 = st.columns(2)
        if c1.button("🤖 에이전트 사이클 실행 (Claude 호출)", type="primary", width="stretch"):
            _run_cycle(True)
        if c2.button("📐 규칙 기반 사이클 (LLM 없음)", width="stretch"):
            _run_cycle(False)
        st.caption("스케줄러로 자동 실행: `python -m logiwise.scheduler --interval 300`")
        last = st.session_state.get("last_cycle")
        if last:
            st.divider()
            _show_cycle(last)

    with tab_history:
        runs = db.runs(30)
        if not runs:
            st.caption("실행 이력이 없습니다.")
        else:
            frame = pd.DataFrame([{
                "ID": r["id"], "시각": r["started_at"][:16].replace("T", " "), "트리거": r["trigger"], "모드": r["mode"], "상태": r["status"],
                "모델": r["model"] or "", "턴": r["num_turns"], "비용($)": round(r["cost_usd"], 4) if r["cost_usd"] else None,
                "소요(ms)": r["duration_ms"], "오류": (r["error"] or "")[:60],
            } for r in runs])
            st.dataframe(frame, width="stretch", hide_index=True)
            pick = st.selectbox("상세 보기", [r["id"] for r in runs], format_func=lambda i: f"실행 #{i}")
            run = db.run(pick)
            if run and run["report_json"]:
                _show_report(json.loads(run["report_json"]))
            if run:
                with st.expander("규칙 스캐너 탐지 내역"):
                    alerts = db.alerts(pick)
                    st.dataframe(pd.DataFrame([{"센터": a["center_code"], "등급": a["severity"], "사유": ", ".join(json.loads(a["reasons"]))} for a in alerts]) if alerts else pd.DataFrame(), width="stretch", hide_index=True)
                if run["tool_log_json"]:
                    with st.expander("도구 호출 기록 (근거 데이터)"):
                        st.json(json.loads(run["tool_log_json"]))
                if run["question"]:
                    with st.expander("에이전트에게 전달한 질문"):
                        st.code(run["question"])

    with tab_chat:
        st.caption("운영 데이터에 대해 자유롭게 질문합니다. 에이전트는 조회만 하며 업무 상태를 바꾸지 않습니다.")
        history = st.session_state.setdefault("chat_history", [])
        for turn in history:
            with st.chat_message(turn["role"]):
                st.write(turn["content"])
                if turn.get("meta"):
                    st.caption(turn["meta"])
        if question := st.chat_input("예: 대전센터 정시출고율이 떨어진 날과 미처리 이벤트를 알려줘"):
            history.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.write(question)
            with st.chat_message("assistant"):
                with st.spinner("조회 중…"):
                    try:
                        answer, sid, meta = agent.chat(question, st.session_state.get("chat_session"))
                    except AgentUnavailable as exc:
                        st.error(str(exc))
                        history.append({"role": "assistant", "content": f"오류: {exc}"})
                    else:
                        st.session_state["chat_session"] = sid
                        caption = f"도구 {', '.join(meta['tools']) or '없음'} · 턴 {meta['num_turns']}" + (f" · ${meta['cost_usd']:.4f}" if meta.get("cost_usd") else "")
                        st.write(answer)
                        st.caption(caption)
                        history.append({"role": "assistant", "content": answer, "meta": caption})
        if history and st.button("대화 초기화"):
            st.session_state.pop("chat_history", None)
            st.session_state.pop("chat_session", None)
            st.rerun()


def _run_cycle(use_agent: bool) -> None:
    with st.spinner("규칙 스캔 후 에이전트 분석 중… (최대 3분)" if use_agent else "규칙 스캔 중…"):
        result = monitor.run_cycle("manual", use_agent=use_agent)
    st.session_state["last_cycle"] = {
        "run_id": result.run_id, "status": result.status, "anomalies": [(r["center_code"], r["name"], r["status"], r["reasons"]) for r in result.anomalies],
        "targets": result.targets, "skipped": result.skipped_pending, "draft_ids": result.draft_ids, "report": result.report,
        "error": result.error, "model": result.model, "cost": result.cost_usd,
    }
    if result.status == "success":
        flash(f"실행 #{result.run_id}: 초안 {len(result.draft_ids)}개 생성. 본사 관제 → 지시 관리에서 승인하세요.")
    st.rerun()


def _show_cycle(last: dict) -> None:
    st.subheader(f"실행 #{last['run_id']} · {last['status']}")
    if last["error"]:
        st.error(last["error"])
    if last["anomalies"]:
        st.markdown("**규칙 스캐너 탐지**")
        for code, name, status, reasons in last["anomalies"]:
            tag = "→ 에이전트 분석" if code in last["targets"] else ("대기 초안 있음, 건너뜀" if code in last["skipped"] else "다음 사이클")
            st.write(f"- {name} ({code}) {status} · {'; '.join(reasons)} · _{tag}_")
    else:
        st.success("이상 센터가 없습니다.")
    if last["report"]:
        _show_report(last["report"])
    if last["draft_ids"]:
        st.info(f"초안 #{', #'.join(map(str, last['draft_ids']))} 대기열 적재 완료.")


def _show_report(report: dict) -> None:
    st.info(report.get("summary", ""))
    for f in report.get("findings", []):
        with st.container(border=True):
            st.markdown(f"**{f['center_code']} · {f['severity']}**")
            st.write("관측: " + f["observation"])
            st.write("가설: " + f["hypothesis"])
            st.write("권장: " + f["recommendation"])
            st.caption("근거: " + ", ".join(f.get("evidence_ids", [])))
    for d in report.get("instruction_drafts", []):
        with st.expander(f"초안 · {d['center_code']} · {d['priority']} · {d['title']}"):
            st.write(d["body"])
