import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homebound import Engine, EngineConfig, Event, Grade, State  # noqa: E402
from homebound.learning import detect_stays, route_match, LearnedRoute  # noqa: E402

KST = timezone(timedelta(hours=9))
HOME = (37.0, 127.0)


def ev(ts, lat, lng, **kw):
    base = dict(activity="automotive", recent_screen_use=True)
    base.update(kw)
    return Event(ts=ts, lat=lat, lng=lng, **base)


def test_far_stationary_is_not_home():
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    start = datetime(2026, 11, 3, 13, 0, tzinfo=KST)
    result = None
    for i in range(4):
        result = engine.update(
            ev(start + timedelta(minutes=30 * i), 37.02, 127.02, activity="still", is_stationary=True)
        )
    assert result is not None
    assert result.distance_m > 250
    assert result.state != State.ARRIVED_HOME
    assert not result.proposal_candidate


def test_quality_gate_excludes_bad_accuracy():
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    start = datetime(2026, 11, 3, 18, 0, tzinfo=KST)
    result = None
    for i in range(4):
        result = engine.update(ev(start + timedelta(minutes=2 * i), 37.0, 127.02, accuracy_m=150))
    assert result is not None
    assert result.state == State.UNKNOWN


def test_companion_unknown_holds_decision():
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    start = datetime(2026, 11, 3, 18, 0, tzinfo=KST)
    result = engine.update(
        ev(start, 37.0, 127.02, activity="unknown", is_stationary=True, recent_screen_use=False)
    )
    assert result.state == State.UNKNOWN
    assert not result.proposal_candidate


def test_passthrough():
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    start = datetime(2026, 11, 3, 19, 0, tzinfo=KST)
    points = [127.03, 127.02, 127.01, 127.001, 126.99, 126.98]
    states = []
    for i, lng in enumerate(points):
        result = engine.update(ev(start + timedelta(minutes=2 * i), 37.0, lng))
        states.append(result.state)
    assert State.GEOFENCE_ENTERED in states
    assert State.PASS_THROUGH in states
    assert states[-1] == State.MOVING


def test_stay_detection():
    start = datetime(2026, 11, 3, 13, 0, tzinfo=KST)
    events = [ev(start + timedelta(minutes=5 * i), 37.02, 127.02, activity="still", is_stationary=True) for i in range(4)]
    stays = detect_stays(events)
    assert len(stays) == 1
    assert stays[0].minutes >= 10


def test_route_match():
    route = LearnedRoute("r1", "office", "home", 25, [(37.0, 127.02), (37.0, 127.01), (37.0, 127.0)])
    events = [ev(datetime(2026, 11, 3, 18, 0, tzinfo=KST), 37.0, 127.02)]
    assert route_match(events, route) > 0.9
