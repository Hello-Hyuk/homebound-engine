# GPS 궤적 귀가 판정 엔진

Android와 iOS 공용 판정 엔진이다. 플랫폼 어댑터가 위치를 공용 이벤트 스키마로
정규화해서 넘기면, 이 엔진이 품질 게이트, 동반 게이트, 특징 계산, 점수,
상태 머신, 통과와 도착 판정을 수행한다.

## 원칙

* 점수만으로 제어하지 않는다. 제안 뒤 사용자가 고른 항목만 실행한다.
* 위치 한 점이나 좌표 뭉침만으로 집이라고 단정하지 않는다. 항상 집 좌표와
  직접 거리를 계산한다.
* 휴대폰 동반이 확인되지 않으면 판정을 보류한다.
* 원시 궤적은 단말에만 둔다. 서버에는 상태 전환과 등급, 근거 요약만 보낸다.
* 귀가 판정 동의와 일상 경로 학습 동의는 분리한다. 학습 동의가 없으면
  장소와 경로, 루틴을 만들지 않는다.
* 숫자 확률은 임계값 확정 전에는 표시하지 않고 등급만 표시한다.

## 실제 집 정보는 저장소에 넣지 않는다

이 저장소에는 실제 주소와 실제 집 좌표가 들어가지 않는다.
집 좌표는 각 단말의 로컬 설정 파일에서만 관리하고, 그 파일은
`.gitignore`로 커밋에서 제외한다. 예시는 `config.example.json`을 본다.

## 사용법

```bash
pip install -e .[dev]
python3 examples/demo.py
python3 -m homebound.cli examples/agent_call.json
pytest -q
```

데모는 합성 궤적만 쓴다. 귀가 접근, 통과, 먼 곳 정지 세 시나리오를
확인할 수 있다. 설치 없이 돌리려면 `PYTHONPATH=src`를 앞에 붙인다.

## 다른 에이전트 사용법

자세한 내용은 `AGENTS.md`와 `docs/agent_usage.md`를 본다. 요약하면
라이브러리, JSON CLI, MCP stdio 서버 세 경로가 있다.

* 라이브러리: `Engine`이 상태를 유지한다
* JSON CLI: `python3 -m homebound.cli examples/agent_call.json`
* MCP: `python3 -m homebound.mcp_server`, 도구 `evaluate_events`,
  `distance_to_home`, `agent_summary`

세 경로 모두 출력에 좌표가 없고, 자동 제어를 하지 않는다.

## 모듈 구조

* `src/homebound/engine.py`: 품질 게이트, 동반 게이트, 특징, 점수, 상태 머신, 제안 정책
* `src/homebound/accumulator.py`: 점 누적과 재생 판정. 누적 파일은 로컬에만 둔다
* `src/homebound/realtime.py`: 점이 들어올 때마다 즉시 판정. 집으로 가는 중인지, 이미 집인지 구분해서 바로 내보낸다
* `src/homebound/learning.py`: 체류 감지, 경로 일치도, Agent 요약 인터페이스
* `examples/demo.py`: 합성 궤적 데모
* `tests/test_engine.py`: 핵심 규칙 테스트

## 제안 정책 요약

* 후보는 귀가 접근 높음 이상, 근접, 이미 도착 전환 시에만 만든다.
* 같은 귀가 세션에서는 1회만, 하루 1에서 2건 이내로 제한한다.
* 오전 9시부터 오후 9시 30분 밖의 귀가 후보는 버리고 아침으로 미루지 않는다.
* 같은 조건에서 3회 연속 거절하면 해당 조건 제안을 중단한다.
* 학습 동의(`learning_enabled`)가 꺼져 있으면 `route_learning_active`와 과거 패턴, 경로 일치 입력은 무시한다.

## 유지보수

* 이 저장소는 공개 저장소로 유지한다. 실측 데이터로 가중치와 임계값을
  조정할 때는 숫자 확률 표시 규칙을 함께 검토한다.
* iOS 지오펜스 지연과 오탐, Android 미룸 같은 플랫폼 실측 결과는
  이슈로 기록하고 엔진 동작에 반영한다.
* 실제 궤적과 실제 주소는 이슈와 커밋, 테스트에도 올리지 않는다.
