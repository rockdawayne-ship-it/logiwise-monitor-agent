"""주기 실행기. `python -m logiwise.scheduler --interval 300`

Streamlit과 별도 프로세스로 돌립니다. Ctrl+C로 중단합니다.
"""
from __future__ import annotations

import argparse
import logging
import time

from . import seed
from .monitor import run_cycle
from .settings import MONITOR


def main() -> None:
    parser = argparse.ArgumentParser(description="LOGIWISE 자율 모니터링 스케줄러")
    parser.add_argument("--interval", type=int, default=int(MONITOR.get("interval_seconds", 300)), help="스캔 주기(초)")
    parser.add_argument("--once", action="store_true", help="한 사이클만 실행")
    parser.add_argument("--rules-only", action="store_true", help="LLM 없이 규칙 기반 초안만 생성")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    seed.seed()
    while True:
        result = run_cycle("scheduler", use_agent=not args.rules_only)
        print(f"[run {result.run_id}] {result.status} | 이상 {len(result.anomalies)} | 대상 {result.targets} "
              f"| 초안 {len(result.draft_ids)} | 대기중복 {result.skipped_pending}" + (f" | 오류 {result.error}" if result.error else ""))
        if args.once:
            break
        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    main()
