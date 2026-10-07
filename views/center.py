"""센터 업무 화면 (PDA 고려: 드롭다운 + 숫자 입력 중심)."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from logiwise import db, rules
from logiwise.db import WorkflowError

from .common import color_rows_by_delay, event_frame, flash, wf_label


def render(center_code: str) -> None:
    row = rules.snapshot(center_code)["centers"][0]
    st.title(f"센터 업무 · {row['name']}")
    st.caption(f"{row['center_code']} · 담당 {row['manager']} · 상태 {row['status']}")

    # ── 본사 지시 배너 (PRD 4.2.1)
    open_wf = [i for i in db.instructions(center_code) if i["status"] != "완료"]
    if open_wf:
        st.warning(f"⚠ 미완료 본사 지시 {len(open_wf)}건이 있습니다. 아래 '본사 지시' 탭에서 확인하세요.")

    # ── 상태 카드 (PRD 4.2.2)
    col = st.columns(4)
    col[0].metric("보관 SKU 수", row["sku_count"])
    col[1].metric("출고 진행 건", len([e for e in db.events(center_code) if e["event_type"] == "미납"]))
    col[2].metric("미납 이벤트", row["open_unpaid_qty"])
    col[3].metric("상태이상 건수", row["open_anomaly_count"])

    tab_flow, tab_events, tab_wf = st.tabs(["입출고 프로세스", "이벤트 조치", f"본사 지시 ({len(open_wf)})"])

    with tab_flow:
        daily = db.inout_daily(center_code, 7)
        latest = daily[-1] if daily else {}
        blocked = rules.bottlenecks(row)
        cols = st.columns(5)
        for i, (stage, key) in enumerate((("입고", "inbound_qty"), ("보관", "storage_qty"), ("피킹", "picking_qty"),
                                           ("패킹", "packing_qty"), ("출고", "outbound_qty"))):
            with cols[i].container(border=True):
                if blocked.get(stage):
                    st.markdown(f"<div style='color:#c00;font-weight:700'>⚠ {stage}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"**{stage}**")
                st.metric("처리량", latest.get(key, 0), label_visibility="collapsed")
        st.caption(f"병목 기준: 미입고 > {rules.RULES['inbound_bottleneck_qty']:g} → 입고 · 상태이상 > 0 → 보관 · 미납 > {rules.RULES['outbound_bottleneck_qty']:g} → 출고")
        if daily:
            frame = pd.DataFrame(daily).melt(id_vars="day", value_vars=["inbound_qty", "outbound_qty"], var_name="구분", value_name="수량")
            frame["구분"] = frame["구분"].map({"inbound_qty": "입고", "outbound_qty": "출고"})
            st.plotly_chart(px.bar(frame, x="day", y="수량", color="구분", barmode="group", title="최근 7일 입출고"), width="stretch")

    with tab_events:
        events = db.events(center_code)
        if not events:
            st.success("처리할 이벤트가 없습니다.")
        else:
            st.dataframe(color_rows_by_delay(event_frame(events)), width="stretch", hide_index=True)
            st.caption("행 색상: 기한 이내 녹 / 24시간 미만 지연 노 / 24시간 이상 지연 적")
            types = db.codes("RESOLVE_TYPE")
            with st.form("resolve_event"):
                target = st.selectbox("이벤트", events, format_func=lambda e: f"#{e['id']} {e['event_type']} {e['product_name'] or ''} 잔여 {e['remaining_qty']}")
                rtype = st.selectbox("조치 유형", [t["code"] for t in types])
                qty = st.number_input("수량", min_value=1, value=max(1, target["remaining_qty"] or 1), step=1)
                memo = st.text_input("메모 (선택)")
                if st.form_submit_button("조치 등록", type="primary", width="stretch"):
                    try:
                        db.resolve_event(target["id"], rtype, int(qty), memo)
                        flash(f"이벤트 #{target['id']} 조치를 등록했습니다.")
                    except WorkflowError as exc:
                        st.error(str(exc))
                        st.stop()
                    st.rerun()

    with tab_wf:
        rows = db.instructions(center_code)
        if not rows:
            st.caption("본사 지시가 없습니다.")
        for r in rows:
            with st.expander(f"{wf_label(r['status'])} · #{r['id']} · {r['title']} · {r['priority']}", expanded=r["status"] != "완료"):
                st.write(r["body"])
                st.caption(f"발송 {r['created_at'][:16].replace('T', ' ')} · 출처 {r['source']}")
                for rep in db.reports(r["id"]):
                    st.info(f"[{rep['reported_at'][:16].replace('T', ' ')}] {rep['action_summary']} · 처리 {rep['handled_qty']} · 잔여 {rep['remaining_qty']}")
                if r["status"] == "지시완료":
                    if st.button("👁️ 확인했습니다", key=f"ack_{r['id']}", type="primary"):
                        try:
                            db.acknowledge_instruction(r["id"])
                            flash(f"지시 #{r['id']} 확인 → 센터확인중")
                        except WorkflowError as exc:
                            st.error(str(exc))
                            st.stop()
                        st.rerun()
                elif r["status"] in ("센터확인중", "조치중"):
                    with st.form(f"report_{r['id']}"):
                        summary = st.text_area("조치 내용", height=90, max_chars=1000)
                        c1, c2 = st.columns(2)
                        handled = c1.number_input("처리 수량", min_value=0, step=1)
                        remaining = c2.number_input("잔여 수량", min_value=0, step=1)
                        if st.form_submit_button("🔧 결과 보고 제출", type="primary", width="stretch"):
                            try:
                                db.submit_report(r["id"], summary, int(handled), int(remaining))
                                flash(f"지시 #{r['id']} 보고 제출 → 조치중")
                            except WorkflowError as exc:
                                st.error(str(exc))
                                st.stop()
                            st.rerun()
