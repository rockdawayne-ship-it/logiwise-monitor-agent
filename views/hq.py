"""본사 관제 화면: KPI 카드, 현황, 7일 추이, 지시 관리(초안 승인 포함)."""
from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from logiwise import db, rules
from logiwise.db import WorkflowError
from logiwise.settings import RULES

from .common import color_rows_by_status, flash, heatmap_style, status_badge, wf_label


def render() -> None:
    st.title("본사 관제")
    snap = rules.snapshot()
    centers = snap["centers"]
    names = {c["center_code"]: c["name"] for c in centers}
    if snap["kpi_day"]:
        st.caption(f"KPI 기준일 {snap['kpi_day']} · 미처리 이벤트는 현재 기준 · {snap['data_kind']}")

    # ── KPI 요약 카드 (PRD 4.1.1)
    rates = [c["on_time_rate"] for c in centers if c["on_time_rate"] is not None]
    avg_rate = sum(rates) / len(rates) if rates else 0
    pending_drafts = db.drafts("대기")
    col = st.columns(5)
    col[0].metric("전국 총 재고량", f"{sum(c['stock_qty'] for c in centers):,}")
    col[1].metric(f"평균 정시출고율 (목표 {RULES['on_time_target']:g}%)", f"{avg_rate:.1f}%", f"{avg_rate - RULES['on_time_target']:+.1f}%p")
    col[2].metric("미납 이벤트 건수", sum(1 for e in db.events() if e["event_type"] == "미납"))
    col[3].metric("이상 발생 센터 수", sum(1 for c in centers if c["status"] in ("주의", "위험")))
    col[4].metric("승인 대기 초안", len(pending_drafts))

    tab_overview, tab_trend, tab_wf = st.tabs(["현황 개요", "KPI 추이 (7일)", f"지시 관리 ({len(pending_drafts)} 초안 대기)"])

    with tab_overview:
        cards = st.columns(4)
        for i, c in enumerate(centers):
            with cards[i % 4].container(border=True):
                st.markdown(f"**{c['name']}** `{c['center_code']}`  \n{status_badge(c['status'])}")
                rate = f"{c['on_time_rate']:.1f}%" if c["on_time_rate"] is not None else "-"
                st.write(f"정시출고율 {rate} · 미처리 {c['open_event_count']}건")
                if c["bottlenecks"]:
                    st.caption("병목: " + ", ".join(c["bottlenecks"]))
        st.subheader("센터별 성과 랭킹")
        frame = pd.DataFrame([{
            "센터": f"{c['name']} ({c['center_code']})", "상태": c["status"],
            "정시출고율(%)": c["on_time_rate"], "미납(개)": c["open_unpaid_qty"], "미입고(개)": c["open_missing_inbound_qty"],
            "상태이상(건)": c["open_anomaly_count"], "기한초과(건)": c["overdue_event_count"], "미완료 지시": c["open_instruction_count"],
        } for c in centers]).sort_values("정시출고율(%)", ascending=False).reset_index(drop=True)
        st.dataframe(color_rows_by_status(frame), width="stretch", hide_index=True)

    with tab_trend:
        trend = pd.DataFrame(db.kpi_trend(None, 7))
        if trend.empty:
            st.info("KPI 데이터가 없습니다.")
        else:
            trend["센터"] = trend["center_code"].map(names)
            fig = px.line(trend, x="day", y="on_time_rate", color="센터", markers=True,
                          labels={"day": "일자", "on_time_rate": "정시출고율(%)"}, title="센터별 정시출고율")
            fig.add_hline(y=RULES["on_time_target"], line_dash="dash", annotation_text=f"목표 {RULES['on_time_target']:g}%")
            st.plotly_chart(fig, width="stretch")
            fig2 = px.bar(trend, x="day", y="unpaid_qty", color="센터", barmode="group",
                          labels={"day": "일자", "unpaid_qty": "미납수량"}, title="센터별 미납수량")
            st.plotly_chart(fig2, width="stretch")
            st.subheader("이상건수 히트맵")
            heat = trend.pivot(index="센터", columns="day", values="anomaly_count").fillna(0).astype(int)
            st.dataframe(heat.style.map(heatmap_style), width="stretch")
            st.caption("셀 색상: 0건 녹 / 1~3건 노 / 4건 이상 적")

    with tab_wf:
        _render_drafts(pending_drafts, names)
        st.divider()
        _render_instructions(names)
        st.divider()
        _render_send_form(names)


def _render_drafts(pending: list[dict], names: dict) -> None:
    st.subheader("에이전트 지시 초안 승인")
    if not pending:
        st.caption("승인 대기 중인 초안이 없습니다. 에이전트 콘솔에서 모니터링 사이클을 실행하면 초안이 생성됩니다.")
        return
    for d in pending:
        with st.expander(f"#{d['id']} · {names.get(d['center_code'], d['center_code'])} · {d['priority']} · {d['title']}", expanded=True):
            run = db.run(d["run_id"])
            st.caption(f"생성 {d['created_at'][:16].replace('T', ' ')} · 분석 #{d['run_id']} ({run['mode'] if run else '-'}) · 근거: "
                       + (", ".join(json.loads(d["evidence_ids"])) or "없음"))
            with st.form(f"draft_{d['id']}"):
                title = st.text_input("제목", d["title"], max_chars=120)
                body = st.text_area("내용", d["body"], height=160, max_chars=3000)
                priority = st.selectbox("우선순위", ["보통", "높음", "긴급"], index=["보통", "높음", "긴급"].index(d["priority"]))
                memo = st.text_input("결정 메모 (선택)")
                c1, c2 = st.columns(2)
                approve = c1.form_submit_button("✅ 승인하고 지시 발송", type="primary", width="stretch")
                reject = c2.form_submit_button("↩ 반려", width="stretch")
            if approve:
                try:
                    iid = db.approve_draft(d["id"], title, body, priority, memo)
                    flash(f"초안 #{d['id']}을(를) 승인했습니다. 지시 #{iid} 발송 (지시완료).")
                except WorkflowError as exc:
                    st.error(str(exc))
                    continue
                st.rerun()
            if reject:
                try:
                    db.reject_draft(d["id"], memo)
                    flash(f"초안 #{d['id']}을(를) 반려했습니다.")
                except WorkflowError as exc:
                    st.error(str(exc))
                    continue
                st.rerun()


def _render_instructions(names: dict) -> None:
    st.subheader("지시 이력")
    rows = db.instructions()
    if not rows:
        st.caption("지시 이력이 없습니다.")
        return
    frame = pd.DataFrame([{
        "ID": r["id"], "상태": wf_label(r["status"]), "센터": names.get(r["center_code"], r["center_code"]), "제목": r["title"],
        "우선순위": r["priority"], "출처": r["source"], "발송": r["created_at"][:16].replace("T", " "),
    } for r in rows])
    st.dataframe(frame, width="stretch", hide_index=True)
    reviewable = [r for r in rows if r["status"] == "조치중"]
    if reviewable:
        st.markdown("**센터 보고 검토 및 승인**")
        for r in reviewable:
            with st.expander(f"#{r['id']} · {names.get(r['center_code'])} · {r['title']}"):
                st.write(r["body"])
                for rep in db.reports(r["id"]):
                    st.info(f"[{rep['reported_at'][:16].replace('T', ' ')}] {rep['action_summary']} · 처리 {rep['handled_qty']} · 잔여 {rep['remaining_qty']}")
                if st.button("✅ 보고 승인 (완료 처리)", key=f"approve_{r['id']}"):
                    try:
                        db.approve_report(r["id"])
                        flash(f"지시 #{r['id']}을(를) 완료 처리했습니다.")
                    except WorkflowError as exc:
                        st.error(str(exc))
                        continue
                    st.rerun()


def _render_send_form(names: dict) -> None:
    st.subheader("직접 지시 발송")
    staged = st.session_state.pop("staged_draft", None)
    with st.form("send_instruction"):
        target = st.selectbox("대상 센터", list(names), format_func=lambda c: f"{names[c]} ({c})",
                              index=list(names).index(staged["center_code"]) if staged and staged.get("center_code") in names else 0)
        title = st.text_input("제목", staged["title"] if staged else "", max_chars=120)
        body = st.text_area("내용", staged["body"] if staged else "", height=140, max_chars=3000)
        priority = st.selectbox("우선순위", ["보통", "높음", "긴급"], index=["보통", "높음", "긴급"].index(staged["priority"]) if staged else 0)
        if st.form_submit_button("📤 지시 발송", type="primary"):
            try:
                iid = db.send_instruction(target, title, body, priority)
                flash(f"지시 #{iid}을(를) {names[target]}에 발송했습니다.")
            except WorkflowError as exc:
                st.error(str(exc))
                return
            st.rerun()
