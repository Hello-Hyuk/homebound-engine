# 다른 에이전트 사용법

## 1. 라이브러리

```python
from homebound import Engine, EngineConfig, Event

engine = Engine(EngineConfig(home_lat=37.0, home_lng=127.0))
result = engine.update(event, eta_minutes=18)
print(result.state, result.grade, result.proposal_candidate)
```

`Engine`은 상태를 유지한다. 플랫폼 어댑터가 Android와 iOS 위치를
`Event` 스키마로 정규화해서 넘긴다고 가정한다.

## 2. JSON CLI

다른 언어의 에이전트나 서브프로세스 호출에 가장 편하다.

```bash
python3 -m homebound.cli examples/agent_call.json
```

입력 필드는 `cli.py` 상단 주석과 `examples/agent_call.json`을 본다.
출력에는 좌표가 없고, 사용자 표시용 문구는 등급만 쓴다.

## 3. MCP 서버

MCP 클라이언트 설정 예는 개념만 적는다. 실제 경로는 설치 위치에 맞춘다.

```json
{
  "mcpServers": {
    "homebound": {
      "command": "python3",
      "args": ["-m", "homebound.mcp_server"]
    }
  }
}
```

## 4. 설치

```bash
pip install git+https://github.com/Hello-Hyuk/homebound-engine.git
```

표준 라이브러리만 쓰므로 추가 의존성은 없다.
