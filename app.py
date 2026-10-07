"""LOGIWISE Streamlit 진입점. 사이드바로 본사 / 센터 / 에이전트 콘솔을 전환합니다."""
import streamlit as st

from logiwise import db, seed
from logiwise.settings import DB_PATH, RULES, today
from views.common import show_flash

st.set_page_config(page_title="LOGIWISE | 물류 성과관리 AI Agent", page_icon="📦", layout="wide")


@st.cache_resource
def _bootstrap(path: str) -> bool:
    seed.seed(path)
    return True


_bootstrap(str(DB_PATH))

with st.sidebar:
    st.markdown("## 📦 LOGIWISE")
    st.caption("물류 성과관리 · 자율 모니터링 AI Agent")
    nav = st.radio("업무 화면", ["본사 관제", "센터 업무", "에이전트 콘솔"], key="nav")
    names = {c["center_code"]: c["name"] for c in db.centers()}
    selected = None
    if nav == "센터 업무":
        selected = st.selectbox("담당 센터", list(names), format_func=lambda c: f"{names[c]} ({c})", key="selected_center")
    pending = len(db.drafts("대기"))
    if pending:
        st.warning(f"승인 대기 초안 {pending}건")
    st.divider()
    with st.expander("판단 기준"):
        st.write(f"정시출고 목표 {RULES['on_time_target']:g}%")
        st.write(f"입고 병목: 미입고 > {RULES['inbound_bottleneck_qty']:g}개")
        st.write("보관 병목: 상태이상 > 0건")
        st.write(f"출고 병목: 미납 > {RULES['outbound_bottleneck_qty']:g}개")
        st.caption(f"위험: 정시출고율 < {RULES['danger_on_time']:g}% 또는 상태이상 ≥ {RULES['danger_anomaly_count']:g}건 · 주의: 목표 미달 또는 미처리 이벤트 존재")
    st.info("교육용 샘플 데이터 · 로컬 단일 사용자")
    if st.button("새로고침", width="stretch"):
        st.rerun()

show_flash()
latest = db.latest_kpi_day()
if latest and latest != today().isoformat():
    st.warning(f"최근 KPI 기준일은 {latest}입니다. 오늘 데이터가 아닙니다.")

if nav == "본사 관제":
    from views.hq import render
    render()
elif nav == "센터 업무":
    from views.center import render
    render(selected)
else:
    from views.agent_console import render
    render()
