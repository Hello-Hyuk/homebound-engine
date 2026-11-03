"""표준 라이브러리만으로 동작하는 최소 MCP 서버 (stdio, JSON-RPC).

다른 에이전트나 MCP 클라이언트가 이 모듈을 도구로 부를 수 있게 한다.
이 서버는 로컬에서만 동작하고, 원시 궤적을 외부로 보내지 않는다.
도구 출력에는 좌표가 들어가지 않는다.

도구:
* evaluate_events: CLI와 같은 입력으로 궤적 판정 결과를 반환한다
* distance_to_home: 현재 점과 집 사이의 거리만 미터로 반환한다
* agent_summary: 좌표 없는 요약 인터페이스를 그대로 반환한다

실행:
  python3 -m homebound.mcp_server
"""

from __future__ import annotations

import json
import sys

from .cli import run as cli_run
from .engine import haversine_m
from .learning import agent_summary

TOOLS = [
    {
        "name": "evaluate_events",
        "description": "GPS 궤적 이벤트 창을 받아 귀가 상태, 등급, 제안 후보를 반환한다. 자동 제어를 하지 않으며, 출력에 좌표가 없다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "config": {"type": "object"},
                "events": {"type": "array"},
                "policy": {"type": "object"},
            },
            "required": ["config", "events"],
        },
    },
    {
        "name": "distance_to_home",
        "description": "현재 위치와 집 좌표 사이의 거리를 미터로만 반환한다. 장소 이름을 단정하지 않는다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lng": {"type": "number"},
                "home_lat": {"type": "number"},
                "home_lng": {"type": "number"},
            },
            "required": ["lat", "lng", "home_lat", "home_lng"],
        },
    },
    {
        "name": "agent_summary",
        "description": "좌표 없는 일상 경로 요약 인터페이스를 반환한다. 학습 동의가 있을 때만 호출한다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "current_place": {"type": "string"},
                "next_place_id": {"type": ["string", "null"]},
                "next_place_probability": {"type": ["number", "null"]},
                "via_place_id": {"type": ["string", "null"]},
                "via_probability": {"type": ["number", "null"]},
                "expected_departure": {"type": ["string", "null"]},
                "expected_arrival": {"type": ["string", "null"]},
                "route_match_value": {"type": "number"},
                "routine_confidence": {"type": "string"},
                "anomaly": {"type": ["string", "null"]},
            },
            "required": ["current_place"],
        },
    },
]


def _text_result(data) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}


def call_tool(name: str, args: dict):
    if name == "evaluate_events":
        return _text_result(cli_run(args))
    if name == "distance_to_home":
        distance = haversine_m(args["lat"], args["lng"], args["home_lat"], args["home_lng"])
        return _text_result({"distance_m": round(distance, 1)})
    if name == "agent_summary":
        summary = agent_summary(
            current_place=args["current_place"],
            next_place_id=args.get("next_place_id"),
            next_place_probability=args.get("next_place_probability"),
            via_place_id=args.get("via_place_id"),
            via_probability=args.get("via_probability"),
            expected_departure=args.get("expected_departure"),
            expected_arrival=args.get("expected_arrival"),
            route_match_value=args.get("route_match_value", 0.0),
            routine_confidence=args.get("routine_confidence", "learning"),
            anomaly=args.get("anomaly"),
        )
        return _text_result(summary.to_dict())
    raise ValueError(f"unknown tool: {name}")


def handle(request: dict) -> dict | None:
    method = request.get("method")
    req_id = request.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": request.get("params", {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "homebound", "version": "0.1.0"},
            },
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = request.get("params", {})
        try:
            result = call_tool(params["name"], params.get("arguments", {}))
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:  # noqa: BLE001 - MCP 클라이언트에 오류를 그대로 전달한다
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(exc)},
            }
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
