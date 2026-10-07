# 가이드 재현 테스트 보고 (2026-10-07)

`docs/CLAUDE_CODE_GUIDE.md`의 Step 0~6 프롬프트를 **새 폴더 `logiwise_agent_repro/`**에서 그대로 실행해 가이드만으로 같은 구조의 에이전트가 나오는지 확인했다.
조건: 폴더에는 `CLAUDE.md`(템플릿)와 `docs/PRD.md`만 두고 시작. 참조 구현 폴더는 읽지 못하게 했다. 각 Step은 독립된 Claude Code 세션이 맡았고, 인증은 Claude Code 구독 로그인(API 키 없음).

## 결과

| Step | 결과 | 검증 |
|---|---|---|
| 0 설계 | `docs/STEP0_PLAN.md` 399줄 | 세 계층·도구 3개·지문·보완 기준 모두 포함 |
| 1 데이터 | 15개 테이블, seed, db.py, 테스트 44개 | `44 passed` |
| 2 규칙 | rules.py + models.py, 테스트 +42 | `86 passed` |
| 3 에이전트 | agent.py(SDK, 도구 3, 검증 7조건), 테스트 +18 | `104 passed`; 실호출 1회차 검증 거부 → 수정 후 성공(sonnet, 5턴, 23.5초, 근거 13개 전부 실제 ID, 초안에 보고 항목 4개) |
| 4 모니터 | monitor.py, scheduler.py, 테스트 +9 | `113 passed`; `--once --rules-only` 2회로 백로그·중복 방지 확인 |
| 5 화면 | app.py + views 4개, 테스트 +11 | `124 passed`; 브라우저(8513)에서 본사/지시 관리 렌더 확인 |
| 6 마무리 | 실 사이클 run 6: sonnet, 6턴, 35.6초, 초안 2건 | 브라우저에서 초안 #5 승인 → 지시 #3(source 에이전트초안) 확인 |

결론: **가이드만으로 재현 가능.** 단, 아래 결함이 드러나 가이드와 템플릿을 고쳤다.

## 발견한 결함과 가이드 수정

| # | 증상 | 원인 | 가이드 수정 |
|---|---|---|---|
| 1 | Step 2~4가 매번 "설계 이름 vs 코드 이름" 충돌 (`list_centers` vs `centers`, `interval_sec` vs `interval_seconds`, `DISPOSITION` 컬럼) | Step 0이 임의 이름을 지음, Step 1이 Step 0 산출물을 참조하지 않음 | Step 0 프롬프트에 "이름은 Step 1~5 프롬프트 우선, docs/STEP0_PLAN.md로 저장" 추가. Step 1에 "STEP0_PLAN.md 참고하되 이름은 프롬프트" 추가 |
| 2 | `AgentReport` 모델을 rules가 쓰면 rules→agent 역방향 import | 모델 위치 미지정 | Step 2에 `logiwise/models.py` 신설 지시, 템플릿 아키텍처에 명시 |
| 3 | 실호출 1·2회차 "조회되지 않은 근거 ID 'WF:1'" | 1회차: 모델이 상세 조회 없이 ID 추측. 2회차: 검증 코드 `len(eid) > 4`가 4글자 `WF:1`을 거부 | Step 3 프롬프트에 "접두어 뒤 1글자 이상" 명시, 검증 실패 두 원인 구분법 추가, 트러블슈팅 행 추가 |
| 4 | `ResultMessage.model` 없음, 비용 필드명 `total_cost_usd` | SDK 실제 필드와 프롬프트 가정 불일치 | Step 3·템플릿에 `model_usage` 키 / `total_cost_usd` 명시 |
| 5 | 선택 인자 도구가 필수 인자로 잡힘 | dict 스키마는 모두 required | Step 3에 JSON Schema dict 사용 명시 |
| 6 | 초안 본문 보고 항목(조치 내용·처리 수량·잔여 수량·완료 예정 시각)이 검증 단계에만 등장 | 프롬프트 누락 | Step 2 rule_report·Step 3 SYSTEM_PROMPT에 추가 |
| 7 | 다크 테마에서 센터 카드·랭킹 행 글자가 안 보임 | HTML 배경색만 지정 | Step 5 프롬프트·템플릿에 `color:#1f1f1f` 지정, 트러블슈팅 행 추가 |
| 8 | views/ 수정 후 새로고침해도 화면 그대로 | 모듈 캐시 | Step 5 하단에 서버 재시작 안내 |
| 9 | 승인 직후 같은 센터가 다음 사이클에 다시 대상 | 중복 방지가 대기 초안 기준 | Step 4 하단에 동작 설명과 선택 규칙 안내 |
| 10 | normalize_code 보정/거부, 초과 조치 거부, overview 비교 대상, 지시 2건 상태, 컬럼 설계 지침이 모호 | Step 1 프롬프트 불충분 | Step 1 프롬프트 보강 |
| 11 | PRD Python 3.10 vs 템플릿 3.11+ | tomllib 요구 | 사전 준비 표에 사유 명시 |

## 실측값 (재현 폴더, Sonnet 5.5, 구독 로그인)

| 실행 | 턴 | 소요 | SDK 추정 비용 |
|---|---|---|---|
| Step 3 단독(`--center C003`) | 5 | 23.5초 | $0.24 |
| Step 6 사이클(C003·C005) | 6 | 35.6초 | $1.12 |

비용은 SDK가 계산한 추정치이며 구독에서는 청구되지 않는다.

## 재현 폴더

`logiwise_agent_repro/` — 그대로 두었다. 참조 구현과 비교 교재로 쓸 수 있다(함수명·컬럼명 대문자 등 스타일 차이 있음).
