"""일상 경로 학습 요약 계층 (v3 14장).

원칙:
* 귀가 판정 동의와 경로 학습 동의는 분리한다. learning_enabled가 False면
  이 모듈을 호출하지 않는다.
* 원시 궤적(L0)은 단말에만 두고, Agent는 L2 이후 요약만 읽는다.
* Agent 조회 결과에는 좌표를 반환하지 않는다.
* LLM은 학습과 판정에 쓰지 않고, 요약 계층을 읽고 제안 문구 생성에만 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .engine import Event, haversine_m


@dataclass
class StaySegment:
    start: datetime
    end: datetime
    lat: float
    lng: float

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


def detect_stays(events: list[Event], radius_m: float = 100.0, min_minutes: float = 10.0) -> list[StaySegment]:
    """반경 100m 안 10분 이상 머문 구간을 체류(L1)로 만든다."""
    stays: list[StaySegment] = []
    if not events:
        return stays
    start = events[0]
    anchor = events[0]
    last = events[0]
    for e in events[1:]:
        if haversine_m(anchor.lat, anchor.lng, e.lat, e.lng) <= radius_m:
            last = e
            continue
        if (last.ts - start.ts) >= timedelta(minutes=min_minutes):
            stays.append(StaySegment(start=start.ts, end=last.ts, lat=anchor.lat, lng=anchor.lng))
        start = e
        anchor = e
        last = e
    if (last.ts - start.ts) >= timedelta(minutes=min_minutes):
        stays.append(StaySegment(start=start.ts, end=last.ts, lat=anchor.lat, lng=anchor.lng))
    return stays


@dataclass
class LearnedRoute:
    """L3 경로 요약. 대표 점은 단말 내부에서만 쓰고, 외부 반환에는 쓰지 않는다."""

    route_id: str
    from_place: str
    to_place: str
    mean_minutes: float
    points: list[tuple[float, float]]  # (lat, lng) 대표 궤적, 단말 전용


def route_match(events: list[Event], route: LearnedRoute, tolerance_m: float = 500.0) -> float:
    """현재 궤적과 학습 경로의 일치도 0~1. 처음 보는 경로는 0에 가깝다."""
    if not events or not route.points:
        return 0.0
    total = 0.0
    for e in events:
        nearest = min(haversine_m(e.lat, e.lng, plat, plng) for plat, plng in route.points)
        total += max(0.0, 1.0 - nearest / tolerance_m)
    return total / len(events)


@dataclass
class AgentSummary:
    """14.3 Agent 조회 인터페이스. 좌표 필드가 없다."""

    current_place: str
    next_place_id: str | None
    next_place_probability: float | None
    via_place_id: str | None
    via_probability: float | None
    expected_departure: str | None
    expected_arrival: str | None
    route_match: float
    routine_confidence: str  # learning | stable
    anomaly: str | None

    def to_dict(self) -> dict:
        return {
            "current_place": self.current_place,
            "next_place": (
                {"id": self.next_place_id, "p": self.next_place_probability, "via": self.via_place_id, "p_via": self.via_probability}
                if self.next_place_id
                else None
            ),
            "expected_departure": self.expected_departure,
            "expected_arrival": self.expected_arrival,
            "route_match": round(self.route_match, 2),
            "routine_confidence": self.routine_confidence,
            "anomaly": self.anomaly,
        }


def agent_summary(
    *,
    current_place: str,
    next_place_id: str | None = None,
    next_place_probability: float | None = None,
    via_place_id: str | None = None,
    via_probability: float | None = None,
    expected_departure: str | None = None,
    expected_arrival: str | None = None,
    route_match_value: float = 0.0,
    routine_confidence: str = "learning",
    anomaly: str | None = None,
) -> AgentSummary:
    return AgentSummary(
        current_place=current_place,
        next_place_id=next_place_id,
        next_place_probability=next_place_probability,
        via_place_id=via_place_id,
        via_probability=via_probability,
        expected_departure=expected_departure,
        expected_arrival=expected_arrival,
        route_match=route_match_value,
        routine_confidence=routine_confidence,
        anomaly=anomaly,
    )
