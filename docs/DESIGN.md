# LOGIWISE 자율 모니터링 에이전트 · 설계 기록

작성일 2026-10-07. 원본 PRD: `../../3기 PRD/물류 성과관리 대시보드 개발_PRD.md`

## 1. 왜 "자율 모니터링" 형태인가

PRD의 핵심 문제는 "본사가 전국 센터 이상을 늦게 알고, 지시-확인-조치-보고 흐름이 끊긴다"이다.
대화형 분석가는 사람이 물어야 움직인다. 자율 모니터링은 사람이 묻기 전에 이상을 찾고 지시 초안까지 준비해 두되,
**발송 결정은 사람이 한다**. 이 경계가 PRD 워크플로우(지시완료 → 센터확인중 → 조치중 → 완료)를 그대로 보존한다.

## 2. 계층 분리: 결정론 → 판단 → 승인

| 계층 | 모듈 | 책임 | LLM |
|---|---|---|---|
| 규칙 | `rules.py` | 등급, 병목, 히트맵, 지연색, 이상 탐지, 지문 | 없음 |
| 판단 | `agent.py` | 이상 센터의 추이·이벤트·지시 이력을 조회해 관측/가설/권장과 초안 작성 | Claude |
| 승인 | `db.approve_draft` + 본사 화면 | 초안 수정·승인·반려. 승인 = `WF_INSTRUCTION` 생성 | 없음 |

LLM이 등급을 바꾸지 못하도록 프롬프트("snapshot의 status를 그대로 쓴다")와 검증(센터 범위·근거 ID)으로 두 번 막는다.

## 3. Claude Agent SDK 선택 이유와 사용법

- 사용자가 Claude Code Max 플랜을 쓰므로 `claude auth login` 인증을 재사용한다. API 키 보관·비용 관리가 필요 없다.
- `query()` 단발 호출. `ClaudeAgentOptions`:
  - `tools=[]` 내장 도구 제거, `mcp_servers={"logiwise": server}`, `allowed_tools=["mcp__logiwise__*"]`
  - `permission_mode="dontAsk"`, `setting_sources=[]`(사용자 CLAUDE.md 무시), `max_turns`, `effort`
  - `output_format={"type":"json_schema","schema": AgentReport.model_json_schema()}`
- 도구는 `@tool` + `create_sdk_mcp_server` 인프로세스 서버. 핸들러가 조회할 때마다 `evidence[evidence_id] = center_code`를 쌓고,
  결과의 모든 `evidence_ids`를 이 사전과 대조한다.
- 대화 모드는 `resume=session_id`로 멀티턴을 이어간다(세션 ID는 Streamlit `session_state`에만 보관).

## 4. 중복 호출 방지 (지문)

`fingerprint = sha1(center, status, bottlenecks, sorted(open_event_ids))[:16]`
대기 중 초안의 지문과 같으면 그 센터는 이번 사이클에서 건너뛴다. 이벤트 처리·등급 변화·초안 반려/승인이 지문을 바꾸거나 대기열에서 제거하므로 자연스럽게 재대상이 된다.
`max_centers_per_cycle`로 한 번에 넘기는 센터 수를 제한하고, 초과분은 다음 사이클이 처리한다(백로그).

## 5. 데이터 모델 보강

PRD 12개 테이블은 그대로 두고 3개를 추가했다.

- `AGENT_RUN`: 사이클/대화 1회 = 1행. 트리거, 범위, 모드(agent/rules), 상태, 모델, 턴, 비용, 질문, 보고서 JSON, 도구 로그, 오류.
- `MON_ALERT`: 사이클마다 규칙 스캐너가 탐지한 센터와 사유, 지문.
- `WF_DRAFT`: 초안 대기열(대기/승인/반려). 승인 시 `WF_INSTRUCTION.source='에이전트초안'`, `draft_id`로 역추적.

## 6. PRD에 없어 보완한 기준

| 항목 | 보완 내용 |
|---|---|
| 센터 등급 | 위험: 정시출고율 < 95% 또는 상태이상 ≥ 4건. 주의: 목표 미달 또는 미처리 이벤트 존재 |
| 이벤트 지연색 | 기한 이내 / 24h 미만 / 24h 이상 |
| 피킹·패킹 병목 | PRD에 기준이 없어 처리량만 표시 |
| 전국 정시출고율 | 센터 단순 평균(주문량 가중 아님) |

## 7. 알려진 제약

- Agent SDK는 Claude Code CLI 프로세스를 띄운다. CLI 미설치·미로그인이면 `AgentUnavailable`로 안내하고 규칙 기반 경로를 제공한다.
- Claude Code 세션 내부(중첩)에서 실행하면 환경변수 간섭이 있을 수 있다. 일반 터미널에서 실행한다.
- Streamlit 재실행 시 선택 탭이 첫 탭으로 돌아간다(Streamlit 기본 동작).
- SQLite 단일 파일. 스케줄러와 Streamlit이 동시에 쓰더라도 트랜잭션은 짧아 `timeout=10`으로 충분하지만, 다중 PC 동시 접근은 지원하지 않는다.
