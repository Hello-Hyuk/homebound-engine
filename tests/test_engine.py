import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homebound import Engine, EngineConfig, Event, Grade, ProposalPolicy, State  # noqa: E402
from homebound import cli, mcp_server  # noqa: E402
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
    for i in range(6):
        result = engine.update(
            ev(start + timedelta(minutes=10 * i), 37.02, 127.02, activity="still", is_stationary=True)
        )
    assert result is not None
    assert result.state == State.STATIONARY  # 유효 점 3개 이상에서 실제로 판정이 돈다
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


def test_sparse_points_accumulate_instead_of_dropping():
    # 이전 모듈 문제: 30분 윈도우가 40분 간격 점을 버려서 유효 점이 계속 2개 이하였다.
    # 수정 뒤에는 점 개수 창으로 마지막 3개 점을 쓰고, 정지 상태로 판정한다.
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    start = datetime(2026, 11, 3, 17, 27, tzinfo=KST)
    result = None
    for i, lng in enumerate([127.02, 127.021, 127.022]):
        ts = start + timedelta(minutes=40 * i)
        result = engine.update(
            ev(ts, 37.02, lng, activity="still", is_stationary=True, recent_screen_use=(i == 2))
        )
    assert result is not None
    assert result.state == State.STATIONARY
    assert result.grade == Grade.LOW
    assert not result.proposal_candidate
    assert any("점 간격" in r for r in result.reasons)


def test_accumulator_dedup_and_replay():
    import tempfile
    from pathlib import Path

    from homebound import accumulate

    history = Path(tempfile.mkdtemp()) / "history.jsonl"
    config = {"home_lat": 37.0, "home_lng": 127.0}
    events = [
        {"ts": "2026-11-03T17:27:00+09:00", "lat": 37.02, "lng": 127.02, "activity": "still", "is_stationary": True},
        {"ts": "2026-11-03T18:07:00+09:00", "lat": 37.02, "lng": 127.021, "activity": "still", "is_stationary": True},
        {"ts": "2026-11-03T18:15:00+09:00", "lat": 37.02, "lng": 127.022, "activity": "still", "is_stationary": True, "recent_screen_use": True},
    ]
    out1 = accumulate(history_path=history, config=config, new_events=events)
    out2 = accumulate(history_path=history, config=config, new_events=events)
    assert out1["total_points"] == 3
    assert out2["added_points"] == 0
    assert out2["total_points"] == 3
    assert out2["latest"]["state"] == "STATIONARY"
    assert out2["latest"]["proposal_candidate"] is False


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


def _arrive(engine, start):
    i = 0
    for lng in [127.03, 127.02, 127.01, 127.001]:
        engine.update(ev(start + timedelta(minutes=2 * i), 37.0, lng), eta_minutes=20 - 4 * i)
        i += 1
    result = None
    for k in range(8):
        result = engine.update(
            ev(start + timedelta(minutes=8 + 2 * k), 37.0, 127.0005, is_stationary=True, activity="still"),
            aux_arrival_signal=True,
        )
    return result


def test_arrived_home_resets_after_leaving():
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    start = datetime(2026, 11, 3, 18, 0, tzinfo=KST)
    assert _arrive(engine, start).state == State.ARRIVED_HOME
    result = None
    for k in range(4):
        result = engine.update(ev(start + timedelta(minutes=40 + 2 * k), 37.0, 127.0 + 0.01 * (k + 1)))
    assert result.state == State.MOVING
    assert engine.session_id is None
    assert not result.proposal_candidate


def test_companion_loss_clears_session():
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    start = datetime(2026, 11, 3, 18, 0, tzinfo=KST)
    for i, lng in enumerate([127.03, 127.02, 127.01, 127.001]):
        engine.update(ev(start + timedelta(minutes=2 * i), 37.0, lng), eta_minutes=20 - 4 * i)
    assert engine.entered_at is not None
    engine.update(ev(start + timedelta(minutes=10), 37.0, 127.001, explicit_with_user=False))
    assert engine.entered_at is None and engine.session_id is None


def test_learning_signals_ignored_without_consent():
    cfg = EngineConfig(home_lat=HOME[0], home_lng=HOME[1], learning_enabled=False, route_learning_active=True)
    engine = Engine(cfg)
    start = datetime(2026, 11, 3, 18, 0, tzinfo=KST)
    result = None
    for i, lng in enumerate([127.05, 127.04, 127.03, 127.02]):
        result = engine.update(
            ev(start + timedelta(minutes=2 * i), 37.0, lng),
            eta_minutes=20 - 3 * i,
            historical_pattern=1.0,
            historical_count=5,
            route_match_value=1.0,
        )
    assert result.features.route_match == 0.0
    assert result.features.historical_pattern == 0.0


def test_proposal_policy():
    policy = ProposalPolicy(max_per_day=1)
    day = datetime(2026, 11, 3, 18, 0, tzinfo=KST)
    assert policy.should_propose(candidate=True, session_id="s1", now=day)
    policy.mark_sent(session_id="s1", now=day)
    assert not policy.should_propose(candidate=True, session_id="s1", now=day)  # 세션 1회
    assert not policy.should_propose(candidate=True, session_id="s2", now=day)  # 하루 한도
    night = datetime(2026, 11, 4, 22, 0, tzinfo=KST)
    assert not policy.should_propose(candidate=True, session_id="s3", now=night)  # 시간 밖
    for _ in range(3):
        policy.record_rejection()
    assert not policy.should_propose(candidate=True, session_id="s4", now=datetime(2026, 11, 5, 12, 0, tzinfo=KST))


def test_cli_run_has_no_coordinates():
    payload = json.loads((Path(__file__).resolve().parents[1] / "examples" / "agent_call.json").read_text("utf-8"))
    text = json.dumps(cli.run(payload), ensure_ascii=False)
    assert '"lat"' not in text and '"lng"' not in text


def test_mcp_notifications_get_no_reply():
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "unknown/notification"}) is None
    reply = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "nope"})
    assert reply["error"]["code"] == -32601
    out = mcp_server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "distance_to_home", "arguments": {"lat": 37.0, "lng": 127.0, "home_lat": 37.0, "home_lng": 127.0}}}
    )
    assert json.loads(out["result"]["content"][0]["text"])["distance_m"] == 0.0


def test_out_of_order_events_rejected():
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    t = datetime(2026, 11, 3, 18, 0, tzinfo=KST)
    engine.update(ev(t, 37.0, 127.02))
    try:
        engine.update(ev(t - timedelta(minutes=1), 37.0, 127.02))
    except ValueError:
        return
    raise AssertionError("ValueError expected")


def test_quick_exit_within_five_minutes_is_passthrough():
    engine = Engine(EngineConfig(home_lat=HOME[0], home_lng=HOME[1]))
    t = datetime(2026, 11, 3, 19, 0, tzinfo=KST)
    states = []
    for i, lng in enumerate([127.03, 127.02, 127.01, 127.001, 126.9980]):  # 마지막은 약 180m
        states.append(engine.update(ev(t + timedelta(minutes=2 * i), 37.0, lng)).state)
    assert states[-1] == State.PASS_THROUGH
