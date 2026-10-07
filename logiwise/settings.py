"""설정 로딩. config.toml → 환경변수 순으로 덮어씁니다."""
from __future__ import annotations

import os
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

with open(ROOT / "config.toml", "rb") as fh:
    _CONFIG = tomllib.load(fh)

DB_PATH = Path(os.getenv("LOGIWISE_DB_PATH", str(ROOT / _CONFIG["database"]["path"])))

AGENT = dict(_CONFIG["agent"])
AGENT["model"] = os.getenv("LOGIWISE_MODEL", AGENT.get("model", "")).strip()
AGENT["cli_path"] = os.getenv("LOGIWISE_CLI_PATH", AGENT.get("cli_path", "")).strip()

MONITOR = dict(_CONFIG["monitor"])
RULES = {key: float(value) for key, value in _CONFIG["rules"].items()}

WORKFLOW_STATUSES = ("지시완료", "센터확인중", "조치중", "완료")
WORKFLOW_ICONS = {"지시완료": "📤", "센터확인중": "👀", "조치중": "🔧", "완료": "✅"}
DRAFT_STATUSES = ("대기", "승인", "반려")


def now() -> datetime:
    return datetime.now(KST)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def today() -> date:
    return now().date()


def normalize_code(value: str, kind: str) -> str:
    """PRD 코드 자릿수 검증. SQLite는 CHAR 길이를 강제하지 않으므로 Python에서 zfill로 맞춥니다."""
    prefix, size = {"center": ("C", 3), "vendor": ("V", 5), "product": ("", 10)}[kind]
    raw = str(value).strip().upper()
    if prefix and raw.startswith(prefix):
        raw = raw[len(prefix):]
    if not raw.isascii() or not raw.isdigit() or len(raw) > size:
        raise ValueError(f"{kind} 코드 형식이 올바르지 않습니다: {value!r}")
    return prefix + raw.zfill(size)
