"""화면 공통 요소."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from logiwise import rules
from logiwise.settings import WORKFLOW_ICONS

STATUS_EMOJI = {"정상": "🟢", "주의": "🟡", "위험": "🔴", "데이터 없음": "⚪"}
LEVEL_COLOR = {"녹": "#d9f2d9", "노": "#fff3b0", "적": "#ffd6d6"}


def flash(message: str) -> None:
    st.session_state["flash"] = message


def show_flash() -> None:
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))


def status_badge(status: str) -> str:
    return f"{STATUS_EMOJI.get(status, '⚪')} {status}"


def wf_label(status: str) -> str:
    return f"{WORKFLOW_ICONS.get(status, '')} {status}"


def color_rows_by_status(df: pd.DataFrame, column: str = "상태"):
    def paint(row):
        color = {"정상": LEVEL_COLOR["녹"], "주의": LEVEL_COLOR["노"], "위험": LEVEL_COLOR["적"]}.get(row[column], "")
        return [f"background-color: {color}" if color else "" for _ in row]
    return df.style.apply(paint, axis=1)


def heatmap_style(value):
    try:
        level = rules.heatmap_level(int(value))
    except (TypeError, ValueError):
        return ""
    return f"background-color: {LEVEL_COLOR[level]}"


def event_frame(events: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame([{
        "ID": e["id"], "유형": e["event_type"], "세부": e["anomaly_type"] or "", "상품": e["product_name"] or "",
        "잔여": e["remaining_qty"], "기한": e["due_at"][:16].replace("T", " "), "지연": rules.event_delay_level(e["due_at"]),
        "메모": e["memo"] or "",
    } for e in events])
    return frame


def color_rows_by_delay(df: pd.DataFrame):
    def paint(row):
        return [f"background-color: {LEVEL_COLOR.get(row['지연'], '')}" for _ in row]
    return df.style.apply(paint, axis=1)
