"""다른 에이전트가 서브프로세스로 부를 수 있는 JSON CLI.

입력은 한 번의 실행 안에 창 단위로 함께 넣는다. CLI는 실행마다 상태가
초기화되므로, 연속 판정이 필요하면 라이브러리를 직접 쓰거나 창 단위
이벤트를 한 번에 넘긴다.

입력 예:
{
  "config": {"home_lat": 37.0, "home_lng": 127.0, "learning_enabled": false},
  "events": [
    {"ts": "2026-11-03T18:00:00+09:00", "lat": 37.0, "lng": 127.05,
     "accuracy_m": 18, "activity": "automotive", "recent_screen_use": true,
     "eta_minutes": 25}
  ]
}

출력에는 좌표가 들어가지 않는다. 거리, 상태, 등급, 근거 요약만 나간다.
숫자 점수는 에이전트 내부 판단용이다. 사용자에게는 등급만 표시한다.

사용법:
  python3 -m homebound.cli < input.json
  python3 -m homebound.cli input.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

from .engine import Engine, EngineConfig, Event, ProposalPolicy


def parse_event(raw: dict) -> tuple[Event, dict]:
    ts_raw = raw["ts"]
    ts = datetime.fromisoformat(ts_raw) if isinstance(ts_raw, str) else ts_raw
    known = {
        "accuracy_m",
        "speed_mps",
        "course_deg",
        "is_stationary",
        "precise",
        "activity",
        "platform",
        "source",
        "geofence_id",
        "geofence_transition",
        "battery_low",
        "watch_connected",
        "car_connected",
        "recent_screen_use",
        "explicit_with_user",
    }
    kwargs = {k: raw[k] for k in known if k in raw}
    event = Event(ts=ts, lat=float(raw["lat"]), lng=float(raw["lng"]), **kwargs)
    options = {
        "eta_minutes": raw.get("eta_minutes"),
        "historical_pattern": raw.get("historical_pattern", 0.0),
        "historical_count": raw.get("historical_count", 0),
        "context": raw.get("context", 0.0),
        "route_match_value": raw.get("route_match_value", 0.0),
        "aux_arrival_signal": raw.get("aux_arrival_signal", False),
    }
    return event, options


def result_to_dict(result, *, ts: str, policy_decision: bool) -> dict:
    return {
        "ts": ts,
        "state": result.state.value,
        "grade": result.grade.value,
        "effective_score": round(result.effective_score, 3),
        "homebound_score": round(result.homebound_score, 3),
        "distance_m": round(result.distance_m, 1),
        "companion": result.companion.value,
        "proposal_candidate": result.proposal_candidate,
        "should_propose": policy_decision,
        "reasons": result.reasons,
        "proposal_text": result.proposal_text if policy_decision else "",
        "features": {
            "distance_trend": round(result.features.distance_trend, 3),
            "heading_alignment": round(result.features.heading_alignment, 3),
            "eta_trend": round(result.features.eta_trend, 3),
            "movement_consistency": round(result.features.movement_consistency, 3),
            "historical_pattern": round(result.features.historical_pattern, 3),
            "context": round(result.features.context, 3),
            "route_match": round(result.features.route_match, 3),
            "location_quality": round(result.features.location_quality, 3),
            "phone_presence": round(result.features.phone_presence, 3),
        },
        # 다른 에이전트와 사용자 모두에게 공통으로 지켜야 할 표시 규칙
        "display_rule": "사용자에게는 등급만 표시하고 숫자 점수는 표시하지 않는다",
    }


def run(payload: dict) -> dict:
    config_raw = payload.get("config", {})
    config = EngineConfig(
        home_lat=float(config_raw["home_lat"]),
        home_lng=float(config_raw["home_lng"]),
        learning_enabled=bool(config_raw.get("learning_enabled", False)),
        route_learning_active=bool(config_raw.get("route_learning_active", False)),
    )
    engine = Engine(config)
    policy = ProposalPolicy(max_per_day=int(payload.get("policy", {}).get("max_per_day", 2)))
    results = []
    for raw in payload.get("events", []):
        event, options = parse_event(raw)
        result = engine.update(event, **options)
        decision = policy.should_propose(
            candidate=result.proposal_candidate,
            session_id=engine.session_id,
            now=event.ts,
        )
        if decision:
            policy.mark_sent(session_id=engine.session_id, now=event.ts)
        ts_text = raw["ts"] if isinstance(raw.get("ts"), str) else event.ts.isoformat()
        results.append(result_to_dict(result, ts=ts_text, policy_decision=decision))
    return {
        "results": results,
        "final_state": results[-1]["state"] if results else "UNKNOWN",
        "final_grade": results[-1]["grade"] if results else "낮음",
        "notes": [
            "이 출력에는 좌표가 없다",
            "제안은 사용자가 고른 항목만 실행한다",
            "자동 제어는 하지 않는다",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    # 누적 모드: python3 -m homebound.cli --history <경로> <입력.json>
    # 입력에 new_events가 있으면 그것을 새 점으로 쓰고, 없으면 events를 쓴다.
    argv = sys.argv if argv is None else argv
    try:
        args = list(argv[1:])
        history_path = None
        if "--history" in args:
            idx = args.index("--history")
            history_path = args[idx + 1]
            del args[idx : idx + 2]
        if args:
            with open(args[0], encoding="utf-8") as f:
                payload = json.load(f)
        else:
            payload = json.load(sys.stdin)
        if history_path is not None:
            # 지연 임포트로 순환 임포트를 피한다.
            from .accumulator import accumulate

            new_events = payload.get("new_events", payload.get("events", []))
            output = accumulate(
                history_path=history_path,
                config=payload.get("config", {}),
                new_events=new_events,
                max_per_day=int(payload.get("policy", {}).get("max_per_day", 2)),
            )
        else:
            output = run(payload)
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        sys.stderr.write(f"입력 오류: {type(exc).__name__}: {exc}\n")
        return 2
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
