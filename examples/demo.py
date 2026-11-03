"""합성 궤적으로 엔진을 돌려보는 데모.

실제 주소와 실제 좌표는 쓰지 않는다. 집은 예시 좌표이다.
시나리오:
1. 귀가 접근: 5km 밖에서 집 쪽으로 꾸준히 이동, ETA 감소
2. 통과: 집 반경에 들어갔다가 5분 안에 벗어남
3. 먼 곳 정지: 집에서 2km 넘게 떨어진 곳에 오래 머무름. 뭉침만으로 집이 되지 않음
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homebound import Engine, EngineConfig, Event, ProposalPolicy  # noqa: E402

KST = timezone(timedelta(hours=9))
HOME = (37.0000, 127.0000)


def ev(ts, lat, lng, **kw):
    base = dict(activity="automotive", recent_screen_use=True)
    base.update(kw)
    return Event(ts=ts, lat=lat, lng=lng, **base)


def run_homebound():
    print("시나리오 1: 귀가 접근")
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    policy = ProposalPolicy()
    start = datetime(2026, 11, 3, 18, 0, tzinfo=KST)
    # 동쪽에서 서쪽 집 방향으로 이동. 위도는 고정하고 경도를 줄인다.
    for i, lng in enumerate([127.0500, 127.0450, 127.0400, 127.0350, 127.0300, 127.0200, 127.0100]):
        ts = start + timedelta(minutes=2 * i)
        eta = 25 - 3 * i
        result = engine.update(ev(ts, 37.0000, lng), eta_minutes=max(eta, 5))
        print(f"  {ts.strftime('%H:%M')} 거리 {result.distance_m:.0f}m 상태 {result.state.value} 등급 {result.grade.value} 점수 {result.effective_score:.2f}")
        if result.proposal_candidate and policy.should_propose(
            candidate=True, session_id=engine.session_id, now=ts
        ):
            print(f"  제안 후보: {result.proposal_text}")
            policy.mark_sent(session_id=engine.session_id, now=ts)


def run_passthrough():
    print("시나리오 2: 통과")
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    start = datetime(2026, 11, 3, 19, 0, tzinfo=KST)
    points = [
        (37.0000, 127.0300),
        (37.0000, 127.0200),
        (37.0000, 127.0100),
        (37.0000, 127.0010),  # 반경 안 진입
        (37.0000, 126.9900),  # 5분 안에 벗어남
        (37.0000, 126.9800),
    ]
    for i, (lat, lng) in enumerate(points):
        ts = start + timedelta(minutes=2 * i)
        result = engine.update(ev(ts, lat, lng))
        print(f"  {ts.strftime('%H:%M')} 거리 {result.distance_m:.0f}m 상태 {result.state.value} 제안 {result.proposal_candidate}")


def run_far_stationary():
    print("시나리오 3: 먼 곳 정지, 뭉침만으로 집이 아님")
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    start = datetime(2026, 11, 3, 13, 0, tzinfo=KST)
    for i in range(6):
        ts = start + timedelta(minutes=10 * i)
        result = engine.update(
            ev(ts, 37.0200, 127.0200, activity="still", is_stationary=True, recent_screen_use=True)
        )
        print(f"  {ts.strftime('%H:%M')} 거리 {result.distance_m:.0f}m 상태 {result.state.value} 제안 {result.proposal_candidate}")


if __name__ == "__main__":
    run_homebound()
    run_passthrough()
    run_far_stationary()
