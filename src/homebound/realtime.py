"""실시간 판정 모드.

목적은 사용자가 말한 그대로이다. 위치 점이 들어올 때마다 기다리지 않고
바로 집으로 가는지, 이미 집인지, 통과인지, 머무는지 판정한다.

동작 방식:
* 입력은 JSON 한 줄이 하나의 위치 점이다. 표준 입력으로 들어오는 대로
  한 줄씩 읽고, 그 줄이 들어온 직후 판정 결과를 한 줄로 바로 내보낸다.
* 누적은 accumulator를 쓴다. 같은 점은 중복으로 쌓지 않고, 전체 이력을
  재생해서 판정하므로, 점이 성기게 들어와도 이전 판정이 날아가지 않는다.
* 출력에는 좌표가 들어가지 않는다. 거리, 상태, 등급, 제안 후보 여부만 나간다.
* 이 모듈 자체는 폰 GPS를 직접 가져오지 않는다. 폰 쪽 수집부가 점을
  이 모듈의 표준 입력으로 넘겨주거나, 누적 파일에 추가해 주는 구조이다.
  메시지 스냅샷으로 쓰는 경우에도 점이 도착하는 순간이 실시간 판정 시점이다.

사용법:
  python3 -m homebound.realtime --history <누적파일> --config <설정.json> < 점들.jsonl
  echo '{"ts": "...", "lat": ..., "lng": ..., "recent_screen_use": true}' | python3 -m homebound.realtime ...

설정 파일 예: {"home_lat": 37.0, "home_lng": 127.0, "learning_enabled": false}
설정이 없으면 --home-lat와 --home-lng로 집 좌표를 받는다.
"""

from __future__ import annotations

import argparse
import json
import sys

from .accumulator import accumulate


def _load_config(args) -> dict:
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            return json.load(f)
    return {
        "home_lat": float(args.home_lat),
        "home_lng": float(args.home_lng),
        "learning_enabled": bool(args.learning_enabled),
        "route_learning_active": bool(args.route_learning_active),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="실시간 GPS 판정: 점이 들어올 때마다 즉시 판정한다")
    parser.add_argument("--history", required=True, help="누적 파일 경로 (로컬 전용)")
    parser.add_argument("--config", default=None, help="집 좌표 설정 JSON 파일")
    parser.add_argument("--home-lat", type=float, default=None)
    parser.add_argument("--home-lng", type=float, default=None)
    parser.add_argument("--learning-enabled", action="store_true")
    parser.add_argument("--route-learning-active", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = _load_config(args)
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        sys.stderr.write(f"설정 오류: {type(exc).__name__}: {exc}\n")
        return 2

    # 표준 입력에서 한 줄씩 실시간으로 받는다. EOF까지 기다리지 않는다.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"error": f"입력 오류: {exc}"}, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        try:
            out = accumulate(history_path=args.history, config=config, new_events=[raw])
        except Exception as exc:  # noqa: BLE001 - 실시간 루프는 한 점의 오류로 멈추지 않는다
            sys.stdout.write(json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        latest = out.get("latest") or {}
        verdict = {
            "ts": latest.get("ts"),
            "state": latest.get("state"),
            "grade": latest.get("grade"),
            "distance_m": latest.get("distance_m"),
            "companion": latest.get("companion"),
            "proposal_candidate": latest.get("proposal_candidate"),
            "should_propose": latest.get("should_propose"),
            "proposal_text": latest.get("proposal_text", ""),
            "reasons": latest.get("reasons", []),
            "total_points": out.get("total_points"),
            "judgement": (
                "집에 도착"
                if latest.get("state") == "ARRIVED_HOME"
                else "집으로 가는 중"
                if latest.get("state") in ("HOMEBOUND", "APPROACHING_HOME")
                else "집으로 가는 중일 가능성"
                if latest.get("state") == "POSSIBLE_HOMEBOUND"
                else "집 반경 진입, 도착 확인 중"
                if latest.get("state") == "GEOFENCE_ENTERED"
                else "통과"
                if latest.get("state") == "PASS_THROUGH"
                else "집에 머무름이 아님, 멀리 정지"
                if latest.get("state") == "STATIONARY"
                else "이동 중"
                if latest.get("state") == "MOVING"
                else "판정 보류"
            ),
        }
        sys.stdout.write(json.dumps(verdict, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
