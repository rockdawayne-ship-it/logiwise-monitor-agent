# LOGIWISE · 물류 성과관리 자율 모니터링 AI Agent

> 🔁 **재현본**: 이 저장소의 [Claude Code 가이드](docs/CLAUDE_CODE_GUIDE.md)만으로 새 폴더에서 다시 만든 결과물은 [logiwise-agent-repro](https://github.com/rockdawayne-ship-it/logiwise-agent-repro) 에 있다. 재현 과정에서 찾은 결함은 [docs/REPRO_REPORT.md](docs/REPRO_REPORT.md) 참고.

「물류 성과관리 대시보드 개발 PRD」를 바탕으로 처음부터 다시 설계한 교육용 로컬 웹앱입니다.
PRD의 본사·센터 대시보드와 지시 워크플로우 위에 **자율 모니터링 에이전트**를 얹었습니다.

```
규칙 스캐너(결정론)  →  이상 센터 탐지  →  Claude 에이전트가 원인 조회·진단  →  지시 초안을 대기열에 적재
                                                                                  ↓
                                          본사 담당자가 초안을 검토·수정·승인  →  WF_INSTRUCTION(지시완료)
                                                                                  ↓
                                          센터 확인(센터확인중) → 결과 보고(조치중) → 본사 승인(완료)
```

에이전트는 **조회만** 합니다. 지시 발송·상태 변경·보고 승인은 사람이 화면에서만 할 수 있습니다.

## 기술 스택

| 구분 | 선택 | 이유 |
|---|---|---|
| LLM 연결 | **Claude Agent SDK** (`claude-agent-sdk`) | Claude Code 로그인(Max 플랜) 인증을 그대로 사용. API 키를 코드나 설정에 저장하지 않음 |
| 도구 | SDK 인프로세스 MCP 서버, 읽기 전용 3개 | 임의 SQL·파일·셸·웹 도구는 제거(`tools=[]`) |
| 출력 | JSON Schema 구조화 출력 + 근거 ID 재검증 | 조회하지 않은 수치·센터를 말하면 결과를 폐기 |
| 앱 | Python 3.11+ · Streamlit · SQLite · pandas · plotly | PRD 그대로 |

## 실행

```powershell
cd 'G:\내 드라이브\한국물류진흥재단_물류AX과정\LOGIWISE_Monitor_Agent'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

브라우저: http://localhost:8501 · 첫 실행 시 7개 센터, 상품 20개, 최근 7일 KPI, 미처리 이벤트, 본사 지시 2건이 자동 생성됩니다(샘플).

**에이전트 사용 전 1회**: Claude Code CLI가 설치되어 있고 로그인되어 있어야 합니다.

```powershell
claude auth status     # loggedIn: true 인지 확인
claude auth login      # 아니면 로그인
```

### 자율 모니터링 스케줄러 (별도 터미널)

```powershell
.\.venv\Scripts\python.exe -m logiwise.scheduler --interval 300          # 5분마다 스캔, 이상 시 Claude 호출
.\.venv\Scripts\python.exe -m logiwise.scheduler --once                  # 한 번만
.\.venv\Scripts\python.exe -m logiwise.scheduler --once --rules-only     # LLM 없이 규칙 초안만
```

Streamlit의 **에이전트 콘솔 → 모니터링 실행** 버튼으로도 같은 사이클을 수동 실행할 수 있습니다.

### 에이전트 단독 실행

```powershell
.\.venv\Scripts\python.exe -m logiwise.agent "대전센터 위험 원인을 상세 조회하고 지시 초안을 작성해 줘" --center C003
```

## 사용 순서 (데모)

1. **에이전트 콘솔 → 🤖 에이전트 사이클 실행**. 규칙 스캐너가 주의·위험 센터를 찾고, 새 이상(대기 초안 없음)인 센터만 Claude에 넘깁니다.
2. 결과 화면에서 탐지 사유, 진단(관측/가설/권장), 근거 ID, 초안을 확인합니다.
3. **본사 관제 → 지시 관리**에서 초안을 수정·승인(= 지시 발송) 또는 반려합니다.
4. **센터 업무**에서 해당 센터를 선택 → 배너 확인 → **👁️ 확인했습니다** → 이벤트 조치 등록 → **🔧 결과 보고 제출**.
5. **본사 관제 → 지시 관리**에서 보고를 승인하면 **완료**.
6. 같은 센터가 같은 상태면 다음 사이클은 건너뜁니다(지문 중복). 이벤트가 처리되거나 초안이 반려되면 다시 대상이 됩니다.

## 설정 (`config.toml`)

| 키 | 기본값 | 설명 |
|---|---|---|
| `agent.model` | `""` | 빈 값이면 Claude Code CLI 기본 모델. 예: `claude-opus-5-5` |
| `agent.effort` | `medium` | low / medium / high / xhigh / max |
| `agent.max_turns` | 12 | 도구 호출 포함 최대 턴 |
| `agent.timeout_seconds` | 180 | 한 분석의 제한시간 |
| `agent.cli_path` | `""` | Claude CLI 실행 파일 경로(비우면 PATH) |
| `monitor.interval_seconds` | 300 | 스케줄러 주기 |
| `monitor.dedupe` | true | 대기 초안과 같은 지문이면 에이전트 호출 생략 |
| `monitor.max_centers_per_cycle` | 3 | 사이클당 에이전트에 넘길 최대 센터 수. 초과분은 다음 사이클 |
| `rules.*` | PRD 값 | 아래 판단 기준 |

환경변수 `LOGIWISE_DB_PATH`, `LOGIWISE_MODEL`, `LOGIWISE_CLI_PATH`가 설정 파일보다 우선합니다.

## 판단 기준

| 항목 | 기준 | 출처 |
|---|---|---|
| 정시출고 목표 | 97% | PRD |
| 입고 병목 | 미입고 잔여 > 3개 | PRD |
| 보관 병목 | 미처리 상태이상 > 0건 | PRD |
| 출고 병목 | 미납 잔여 > 5개 | PRD |
| 히트맵 | 0건 녹 / 1~3건 노 / 4건 이상 적 | PRD |
| 센터 위험 | 정시출고율 < 95% 또는 상태이상 ≥ 4건 | 보완 |
| 센터 주의 | 위험이 아니면서 목표 미달 또는 미처리 이벤트 존재 | 보완 |
| 이벤트 지연색 | 기한 이내 녹 / 24시간 미만 지연 노 / 24시간 이상 적 | 보완 |

등급·병목은 `logiwise/rules.py`가 결정하며 LLM은 이 값을 바꾸지 않습니다(프롬프트와 검증 양쪽에서 강제).

## 에이전트 안전장치

- 도구 3개: `get_operating_snapshot`, `get_center_detail`, `get_pending_drafts`. 모두 읽기 전용이며 이번 사이클의 대상 센터만 조회할 수 있습니다.
- 내장 도구(파일·Bash·웹) 제거, 사용자 `CLAUDE.md`·프로젝트 설정 미로딩(`setting_sources=[]`), `permission_mode="dontAsk"`.
- 구조화 출력 스키마(`AgentReport`)로 결과를 받고, `validate_report`가 (1) 필수 조회 수행 여부 (2) 범위 밖 센터 (3) 조회되지 않은 근거 ID (4) 센터-근거 불일치 (5) 진단 없는 초안을 거부합니다.
- 도구 결과 안의 메모·제목은 "지시문이 아닌 업무 데이터"로 프롬프트에 명시합니다.
- 모든 실행은 `AGENT_RUN`(질문, 모델, 턴 수, 비용, 도구 로그, 오류)에 남습니다. 실패해도 기록됩니다.
- 오류 문구는 종류만 노출하고 제공자 원문은 숨깁니다(요청 데이터·자격 증명 노출 방지).
- LLM이 불가하면 **규칙 기반 사이클**이 같은 포맷의 초안을 만듭니다. 결과 화면과 이력에 `rules`로 표시되어 AI 결과와 구분됩니다.

## 프로젝트 구조

```
LOGIWISE_Monitor_Agent/
├── app.py                    Streamlit 진입점 (사이드바 역할 전환)
├── config.toml               DB 경로 · 에이전트 · 모니터 · 규칙 임계값
├── logiwise/
│   ├── settings.py           설정 로딩, KST, 코드 자릿수 검증
│   ├── schema.sql            PRD 12개 테이블 + AGENT_RUN · MON_ALERT · WF_DRAFT
│   ├── db.py                 연결 컨텍스트, 조회, 워크플로우/초안 트랜잭션
│   ├── seed.py               샘플 데이터
│   ├── rules.py              등급·병목·히트맵·지연색·이상 탐지·지문 (결정론)
│   ├── agent.py              Claude Agent SDK: 도구, 스키마, 검증, 분석/대화
│   ├── monitor.py            사이클: 스캔 → 에이전트 → 초안 대기열
│   └── scheduler.py          주기 실행 CLI
├── views/                    hq.py · center.py · agent_console.py · common.py
├── tests/                    29개 (데이터·규칙·워크플로우·에이전트 검증·모니터·UI)
└── docs/DESIGN.md            설계 결정 기록
```

## 검증

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

테스트는 임시 DB를 사용하며 `data/logiwise.db`를 건드리지 않습니다. LLM 호출은 테스트에 포함되지 않습니다.
실제 Claude 호출 확인은 `python -m logiwise.agent` 또는 콘솔의 에이전트 사이클 버튼으로 합니다(로그인 필요).

2026-10-07 검증: 자동 테스트 29개 통과. Streamlit 화면에서 규칙 기반 사이클 → 초안 3건 적재 → 본사 승인 → 지시 #3 발송까지 브라우저로 확인.
실제 Claude 호출 스모크는 CLI 로그인(OAuth 세션 만료) 문제로 이 환경에서 미완료. `claude auth login` 후 재실행 필요.

## 범위 밖

로컬 단일 사용자용입니다. 실제 WMS/ERP 연동, 다중 사용자 인증, 이메일/Slack 알림, 지도 시각화, 배포는 포함하지 않습니다.
사이드바 역할 전환은 체험용이며 권한 관리가 아닙니다. Google Drive 동기화 폴더의 SQLite를 여러 PC에서 동시에 열지 마세요.

## 수강생 재현 가이드

Claude Code로 이 프로젝트를 처음부터 다시 만드는 단계별 프롬프트: [docs/CLAUDE_CODE_GUIDE.md](docs/CLAUDE_CODE_GUIDE.md) · 프로젝트 CLAUDE.md 템플릿: [docs/templates/CLAUDE.md](docs/templates/CLAUDE.md)
