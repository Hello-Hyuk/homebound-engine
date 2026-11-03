"""데이터 누적 판정기.

엔진 자체는 호출할 때만 동작하므로, 계속 판정하려면 점들을 어딘가에
쌓아두고 매번 전체를 다시 돌려야 한다. 이 모듈이 그 역할을 한다.

* 누적 파일은 호출자가 정한 로컬 경로에만 쓴다. 공개 저장소에는
  실제 궤적 파일을 넣지 않는다.
* 같은 시각과 같은 좌표의 중복 점은 한 번만 쌓는다.
* 판정은 전체 이력을 처음부터 다시 돌리는 재생 방식이다. 엔진 상태
  직렬화의 어긋남을 피하고, 모듈이 바뀌어도 이력만 있으면 다시
  계산할 수 있다.
* 출력에는 좌표가 들어가지 않는다. 누적 파일 자체는 로컬에만 둔다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .cli import parse_event, result_to_dict
from .engine import Engine, EngineConfig, ProposalPolicy


def _event_to_record(raw: dict) -> dict:
    # 원본 입력은 그대로 저장한다. 좌표가 들어 있으므로 로컬 전용이다.
    return dict(raw)


def accumulate(
    *,
    history_path: str | Path,
    config: dict,
    new_events: list[dict],
    max_per_day: int = 2,
) -> dict:
    path = Path(history_path)
    history: list[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                history.append(json.loads(line))

    seen = {(e.get("ts"), e.get("lat"), e.get("lng")) for e in history}
    added = 0
    for raw in new_events:
        key = (raw.get("ts"), raw.get("lat"), raw.get("lng"))
        if key in seen:
            continue
        history.append(_event_to_record(raw))
        seen.add(key)
        added += 1

    # 시간 순으로 정렬해서 재생한다.
    def _ts_key(e: dict):
        try:
            return datetime.fromisoformat(str(e["ts"]))
        except Exception:
            return datetime.min

    history.sort(key=_ts_key)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in history:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    engine = Engine(
        EngineConfig(
            home_lat=float(config["home_lat"]),
            home_lng=float(config["home_lng"]),
            learning_enabled=bool(config.get("learning_enabled", False)),
            route_learning_active=bool(config.get("route_learning_active", False)),
        )
    )
    policy = ProposalPolicy(max_per_day=max_per_day)
    results = []
    for raw in history:
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

    last = results[-1] if results else None
    return {
        "history_path": str(path),
        "total_points": len(history),
        "added_points": added,
        "first_ts": history[0]["ts"] if history else None,
        "last_ts": history[-1]["ts"] if history else None,
        "results": results,
        "latest": last,
        "notes": [
            "이 출력에는 좌표가 없다",
            "누적 파일은 로컬에만 둔다",
            "제안은 사용자가 고른 항목만 실행한다",
            "자동 제어는 하지 않는다",
        ],
    }
