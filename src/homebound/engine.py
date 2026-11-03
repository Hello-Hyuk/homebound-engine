"""공용 귀가 판정 엔진.

플랫폼 어댑터(Android Fused Location, iOS CLLocationUpdate 등)는
이 파일의 Event 스키마로 정규화해서 넘긴다고 가정한다. 엔진 자체는
플랫폼에 의존하지 않는다.

핵심 규칙 (v3 명세 요약):
* 정확도 100m 초과 점은 궤적 판정에서 제외한다.
* 휴대폰 동반이 UNKNOWN 또는 NOT_WITH_USER이면 판정을 보류한다.
* 좌표 뭉침만으로 집이라고 단정하지 않는다. 항상 집 좌표와 거리를 직접 계산한다.
* 점수만으로 제어하지 않는다. 제안 후보만 만들고, 실행은 사용자가 고른 항목만 한다.
* 임계값 확정 전에는 숫자 확률을 외부에 표시하지 않고 등급만 표시한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum


EARTH_R = 6_371_000.0
HOME_ENTER_M = 150.0
HOME_EXIT_M = 250.0
HOME_MID_M = 1_000.0
ARRIVAL_DWELL = timedelta(minutes=10)
PASS_THROUGH_WINDOW = timedelta(minutes=5)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 사이의 대권 거리를 미터로 반환한다."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """lat1/lng1에서 lat2/lng2를 바라보는 방위각(0~360도)."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlmb = math.radians(lng2 - lng1)
    y = math.sin(dlmb) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff_deg(a: float, b: float) -> float:
    """두 방위각 사이의 최소 차이(0~180도)."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def quality_weight(accuracy_m: float | None) -> float:
    """v3 8.1 정확도 구간별 가중치."""
    if accuracy_m is None:
        return 0.0
    if accuracy_m <= 30:
        return 1.0
    if accuracy_m <= 60:
        return 0.5
    if accuracy_m <= 100:
        return 0.25  # 거리 계산만 사용한다는 뜻의 낮은 가중치
    return 0.0


class Grade(str, Enum):
    LOW = "낮음"
    MEDIUM = "중간"
    HIGH = "높음"
    VERY_HIGH = "매우 높음"


class State(str, Enum):
    UNKNOWN = "UNKNOWN"
    STATIONARY = "STATIONARY"
    MOVING = "MOVING"
    POSSIBLE_HOMEBOUND = "POSSIBLE_HOMEBOUND"
    HOMEBOUND = "HOMEBOUND"
    APPROACHING_HOME = "APPROACHING_HOME"
    GEOFENCE_ENTERED = "GEOFENCE_ENTERED"
    ARRIVED_HOME = "ARRIVED_HOME"
    PASS_THROUGH = "PASS_THROUGH"


class CompanionStatus(str, Enum):
    WITH_USER = "WITH_USER"
    LIKELY = "LIKELY"
    UNKNOWN = "UNKNOWN"
    NOT_WITH_USER = "NOT_WITH_USER"


@dataclass
class Event:
    """공용 이벤트 스키마 (v3 6장)."""

    ts: datetime
    lat: float
    lng: float
    accuracy_m: float = 30.0
    speed_mps: float | None = None
    course_deg: float | None = None
    is_stationary: bool = False
    precise: bool = True
    activity: str = "unknown"  # automotive | cycling | walking | still | unknown
    platform: str = "android"
    source: str = "live"  # geofence | live | significant | visit | manual
    geofence_id: str | None = None
    geofence_transition: str | None = None
    battery_low: bool = False
    # 동반 판정용 보조 신호. 플랫폼 어댑터가 채운다.
    watch_connected: bool = False
    car_connected: bool = False  # 차량 Bluetooth / CarPlay
    recent_screen_use: bool = False
    explicit_with_user: bool | None = None  # True: 명시 확인, False: 명시 부정


def companion_status(event: Event, window: list[Event]) -> CompanionStatus:
    """v3 8.2 동반 Gate. 불명이면 판정을 보류하는 것이 핵심이다."""
    if event.explicit_with_user is True:
        return CompanionStatus.WITH_USER
    if event.explicit_with_user is False:
        return CompanionStatus.NOT_WITH_USER
    if event.watch_connected:
        return CompanionStatus.WITH_USER
    if (
        event.car_connected
        or event.recent_screen_use
        or event.activity in ("automotive", "cycling", "walking")
    ):
        return CompanionStatus.LIKELY
    # 장시간 정지 + 활동 없음 + 보조 신호 없음이면 UNKNOWN
    recent = window[-6:] if window else []
    if event.is_stationary and all(
        (not e.watch_connected and not e.car_connected and not e.recent_screen_use)
        for e in recent
    ):
        return CompanionStatus.UNKNOWN
    return CompanionStatus.UNKNOWN


@dataclass
class Features:
    distance_trend: float = 0.0
    heading_alignment: float = 0.0
    eta_trend: float = 0.0
    movement_consistency: float = 0.0
    historical_pattern: float = 0.0
    context: float = 0.0
    route_match: float = 0.0
    location_quality: float = 0.0
    phone_presence: float = 0.0


@dataclass
class EngineResult:
    state: State
    grade: Grade
    effective_score: float
    homebound_score: float
    features: Features
    distance_m: float
    companion: CompanionStatus
    proposal_candidate: bool
    reasons: list[str] = field(default_factory=list)
    # 제안 메시지에 들어갈 요약만 담는다. 좌표는 담지 않는다.
    proposal_text: str = ""


@dataclass
class EngineConfig:
    home_lat: float
    home_lng: float
    # 학습 동의가 있을 때만 True. 없으면 장소/경로/루틴을 만들지 않는다.
    learning_enabled: bool = False
    # 다음 목적지 등 학습 신호가 있을 때만 RouteMatch를 쓴다.
    route_learning_active: bool = False


class Engine:
    """최근 15~30분 또는 유효 점 4~6개 창을 보는 공용 엔진."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self.state = State.UNKNOWN
        self.window: list[Event] = []
        self.eta_history: list[tuple[datetime, float]] = []
        self.high_streak = 0
        self.entered_at: datetime | None = None
        self.min_distance_since_enter: float | None = None
        self.session_id: str | None = None

    # -- 내부 계산 -----------------------------------------------------
    def _distance(self, event: Event) -> float:
        return haversine_m(event.lat, event.lng, self.config.home_lat, self.config.home_lng)

    def _valid_points(self, events: list[Event]) -> list[Event]:
        out: list[Event] = []
        prev: Event | None = None
        for e in events:
            if e.accuracy_m is not None and e.accuracy_m > 100:
                continue
            if prev is not None:
                dt = (e.ts - prev.ts).total_seconds()
                if dt > 0 and haversine_m(prev.lat, prev.lng, e.lat, e.lng) / dt >= 70:
                    continue  # 튐으로 보고 버린다
            out.append(e)
            prev = e
        return out

    def _features(
        self,
        valid: list[Event],
        companion: CompanionStatus,
        eta_minutes: float | None,
        historical_pattern: float,
        historical_count: int,
        context: float,
        route_match_value: float,
    ) -> Features:
        distances = [self._distance(e) for e in valid]
        # DistanceTrend: 단조 감소 비율과 감소량을 함께 본다. 속도 자체는 보지 않는다.
        decreases = 0
        steps = 0
        for a, b in zip(distances, distances[1:]):
            steps += 1
            if b < a:
                decreases += 1
        monotonic = (decreases / steps) if steps else 0.0
        total_drop = max(0.0, distances[0] - distances[-1]) if len(distances) >= 2 else 0.0
        drop_ratio = min(1.0, total_drop / 500.0) if distances else 0.0
        distance_trend = monotonic * (0.5 + 0.5 * drop_ratio)

        # HeadingAlignment: 최근 이동 벡터와 집 방향 사이의 각도.
        heading_alignment = 0.0
        if len(valid) >= 2:
            first, last = valid[0], valid[-1]
            move_dist = haversine_m(first.lat, first.lng, last.lat, last.lng)
            acc_sum = (first.accuracy_m or 0) + (last.accuracy_m or 0)
            if move_dist > acc_sum and move_dist > 0:
                move_bearing = bearing_deg(first.lat, first.lng, last.lat, last.lng)
                home_bearing = bearing_deg(last.lat, last.lng, self.config.home_lat, self.config.home_lng)
                diff = angle_diff_deg(move_bearing, home_bearing)
                heading_alignment = max(0.0, 1.0 - diff / 90.0) if diff < 90 else 0.0

        # ETATrend: ETA 감소 여부와 30분 이내 진입.
        # eta_history에는 현재 호출분이 이미 들어 있으므로, 직전 값은 뒤에서 두 번째이다.
        eta_trend = 0.0
        if eta_minutes is not None:
            prev_eta = self.eta_history[-2][1] if len(self.eta_history) >= 2 else None
            decreasing = prev_eta is not None and eta_minutes < prev_eta
            if decreasing:
                eta_trend = 0.7
            if eta_minutes <= 30:
                eta_trend = max(eta_trend, 0.7)
                if decreasing:
                    eta_trend = 1.0

        moving = [e for e in valid if not e.is_stationary]
        movement_consistency = (len(moving) / len(valid)) if valid else 0.0

        # 1회 반복은 패턴으로 보지 않는다.
        hist = historical_pattern if historical_count >= 2 else 0.0

        weights = [quality_weight(e.accuracy_m) for e in valid]
        location_quality = (sum(weights) / len(weights)) if weights else 0.0

        phone_presence = {
            CompanionStatus.WITH_USER: 1.0,
            CompanionStatus.LIKELY: 0.8,
        }.get(companion, 0.0)

        return Features(
            distance_trend=distance_trend,
            heading_alignment=heading_alignment,
            eta_trend=eta_trend,
            movement_consistency=movement_consistency,
            historical_pattern=hist,
            context=max(0.0, min(1.0, context)),
            route_match=route_match_value if self.config.route_learning_active else 0.0,
            location_quality=location_quality,
            phone_presence=phone_presence,
        )

    @staticmethod
    def _score(features: Features, eta_available: bool, route_learning_active: bool) -> tuple[float, float]:
        if route_learning_active:
            weights = {
                "distance_trend": 0.30,
                "heading_alignment": 0.25,
                "eta_trend": 0.20,
                "movement_consistency": 0.10,
                "historical_pattern": 0.05,
                "context": 0.05,
                "route_match": 0.05,
            }
        else:
            weights = {
                "distance_trend": 0.30,
                "heading_alignment": 0.25,
                "eta_trend": 0.20,
                "movement_consistency": 0.10,
                "historical_pattern": 0.10,
                "context": 0.05,
                "route_match": 0.0,
            }
        if not eta_available:
            # ETA 실패 시 나머지 가중치를 비례 재분배한다.
            eta_w = weights.pop("eta_trend")
            total = sum(weights.values())
            weights = {k: v / total for k, v in weights.items()}
            _ = eta_w
        values = {
            "distance_trend": features.distance_trend,
            "heading_alignment": features.heading_alignment,
            "eta_trend": features.eta_trend,
            "movement_consistency": features.movement_consistency,
            "historical_pattern": features.historical_pattern,
            "context": features.context,
            "route_match": features.route_match,
        }
        homebound = sum(weights[k] * values[k] for k in weights)
        effective = homebound * features.location_quality * features.phone_presence
        return homebound, effective

    @staticmethod
    def _grade(effective: float, eta_available: bool, route_learning_active: bool, route_match_value: float) -> Grade:
        grade = (
            Grade.VERY_HIGH
            if effective >= 0.80
            else Grade.HIGH
            if effective >= 0.65
            else Grade.MEDIUM
            if effective >= 0.40
            else Grade.LOW
        )
        # ETA 실패 시 최대 등급은 높음. 처음 보는 경로도 최대 높음.
        if not eta_available and grade == Grade.VERY_HIGH:
            grade = Grade.HIGH
        if route_learning_active and route_match_value == 0.0 and grade == Grade.VERY_HIGH:
            grade = Grade.HIGH
        return grade

    # -- 상태 머신 -----------------------------------------------------
    def update(
        self,
        event: Event,
        *,
        eta_minutes: float | None = None,
        historical_pattern: float = 0.0,
        historical_count: int = 0,
        context: float = 0.0,
        route_match_value: float = 0.0,
        aux_arrival_signal: bool = False,  # 집 Wi-Fi, 집 안 기기 활동, 사용자 확인 중 1개 이상
        precise: bool | None = None,
    ) -> EngineResult:
        if precise is not None:
            event.precise = precise
        if not event.precise:
            # 대략 위치 권한이면 방향 계산을 제외하고 최대 등급을 중간으로 제한한다.
            pass

        self.window.append(event)
        # 최근 30분 창만 유지한다.
        cutoff = event.ts - timedelta(minutes=30)
        self.window = [e for e in self.window if e.ts >= cutoff]
        if eta_minutes is not None:
            self.eta_history.append((event.ts, eta_minutes))
            self.eta_history = [(t, v) for t, v in self.eta_history if t >= cutoff]

        companion = companion_status(event, self.window)
        distance = self._distance(event)
        valid = self._valid_points(self.window[-6:])
        reasons: list[str] = []

        if companion in (CompanionStatus.UNKNOWN, CompanionStatus.NOT_WITH_USER):
            self.state = State.UNKNOWN
            reasons.append("휴대폰 동반이 확인되지 않아 판정을 보류한다")
            return EngineResult(
                state=self.state,
                grade=Grade.LOW,
                effective_score=0.0,
                homebound_score=0.0,
                features=Features(phone_presence=0.0),
                distance_m=distance,
                companion=companion,
                proposal_candidate=False,
                reasons=reasons,
            )

        if len(valid) < 3:
            self.state = State.UNKNOWN
            reasons.append("유효 점이 3개 미만이라 판정을 보류한다")
            return EngineResult(
                state=self.state,
                grade=Grade.LOW,
                effective_score=0.0,
                homebound_score=0.0,
                features=Features(),
                distance_m=distance,
                companion=companion,
                proposal_candidate=False,
                reasons=reasons,
            )

        features = self._features(
            valid, companion, eta_minutes, historical_pattern, historical_count, context, route_match_value
        )
        # 대략 위치 권한이면 방향을 제외한다.
        if not event.precise:
            features.heading_alignment = 0.0
        homebound, effective = self._score(features, eta_minutes is not None, self.config.route_learning_active)
        grade = self._grade(effective, eta_minutes is not None, self.config.route_learning_active, route_match_value)
        if not event.precise and grade in (Grade.HIGH, Grade.VERY_HIGH):
            grade = Grade.MEDIUM

        # 상태 전이
        prev_state = self.state
        if self.state == State.PASS_THROUGH:
            self.state = State.MOVING
            self.session_id = None
        if event.is_stationary and distance > HOME_EXIT_M and self.state in (State.UNKNOWN,):
            self.state = State.STATIONARY
        elif not event.is_stationary and self.state == State.UNKNOWN:
            self.state = State.MOVING

        if grade == Grade.MEDIUM and self.state in (State.MOVING, State.STATIONARY):
            self.state = State.POSSIBLE_HOMEBOUND
        if grade in (Grade.HIGH, Grade.VERY_HIGH):
            self.high_streak += 1
        else:
            self.high_streak = 0
        if self.high_streak >= 2 and self.state in (State.POSSIBLE_HOMEBOUND, State.MOVING):
            self.state = State.HOMEBOUND
        if grade == Grade.LOW and self.state == State.POSSIBLE_HOMEBOUND:
            self.state = State.MOVING
        if self.state in (State.POSSIBLE_HOMEBOUND, State.HOMEBOUND, State.APPROACHING_HOME) and self.session_id is None:
            self.session_id = event.ts.isoformat()

        eta_decreasing = len(self.eta_history) >= 2 and self.eta_history[-1][1] < self.eta_history[-2][1]
        if self.state == State.HOMEBOUND and distance <= HOME_MID_M and (eta_decreasing or eta_minutes is not None and eta_minutes <= 30):
            self.state = State.APPROACHING_HOME

        if distance <= HOME_ENTER_M and self.state in (
            State.APPROACHING_HOME,
            State.HOMEBOUND,
            State.POSSIBLE_HOMEBOUND,
            State.MOVING,
        ):
            self.state = State.GEOFENCE_ENTERED
            if self.entered_at is None:
                self.entered_at = event.ts
                self.min_distance_since_enter = distance
                self.session_id = event.ts.isoformat()
        if self.state == State.GEOFENCE_ENTERED and self.entered_at is not None:
            assert self.min_distance_since_enter is not None
            self.min_distance_since_enter = min(self.min_distance_since_enter, distance)
            dwell = event.ts - self.entered_at
            if distance > HOME_EXIT_M:
                # 5분 내 이탈 또는 250m 초과: 통과
                self.state = State.PASS_THROUGH
                self.entered_at = None
                reasons.append("집 반경을 벗어나 통과로 판정한다")
            elif dwell >= ARRIVAL_DWELL and event.is_stationary and aux_arrival_signal:
                self.state = State.ARRIVED_HOME
                reasons.append("10분 이상 머무름과 보조 신호로 도착을 확정한다")
            elif dwell >= ARRIVAL_DWELL and event.is_stationary:
                reasons.append("도착 후보이다. 보조 신호가 없어 확정하지 않는다")
        # 통과 상태는 이번 업데이트 결과로 남기고, 다음 업데이트에서 MOVING으로 돌아간다.
        # 통과는 외출로 보지 않는다.

        if self.state in (State.HOMEBOUND, State.APPROACHING_HOME, State.ARRIVED_HOME):
            if distance < (self.min_distance_since_enter or distance):
                pass
        if distance > HOME_EXIT_M and self.state == State.HOMEBOUND:
            # 거리 증가 지속은 별도 호출에서 window로 확인한다. 여기서는 상태만 유지한다.
            pass

        if prev_state != self.state:
            reasons.append(f"상태 전환 {prev_state.value}에서 {self.state.value}로")

        proposal_candidate = self.state in (State.HOMEBOUND, State.APPROACHING_HOME, State.ARRIVED_HOME) and grade in (
            Grade.HIGH,
            Grade.VERY_HIGH,
        )
        proposal_text = ""
        if proposal_candidate:
            kind = "이미 도착" if self.state == State.ARRIVED_HOME else "귀가 접근"
            proposal_text = (
                f"[{kind} · {grade.value}] 집까지 약 {distance / 1000:.1f}km. "
                f"근거: 휴대폰 위치 거리 변화, 이동 방향, 도착 예상 시간. "
                "귀가 준비를 할까요? 사용자가 고른 항목만 실행한다."
            )
        return EngineResult(
            state=self.state,
            grade=grade,
            effective_score=effective,
            homebound_score=homebound,
            features=features,
            distance_m=distance,
            companion=companion,
            proposal_candidate=proposal_candidate,
            reasons=reasons,
            proposal_text=proposal_text,
        )


class ProposalPolicy:
    """v3 11장 제안 정책. 판정은 즉시 하고, 발송만 정책을 거친다."""

    def __init__(self, max_per_day: int = 2):
        self.max_per_day = max_per_day
        self.sent_by_day: dict[str, int] = {}
        self.sent_sessions: set[str] = set()
        self.rejections: dict[str, int] = {}

    def should_propose(
        self,
        *,
        candidate: bool,
        session_id: str | None,
        now: datetime,
        is_error: bool = False,
        condition_key: str = "homebound",
    ) -> bool:
        if not candidate:
            return False
        if self.rejections.get(condition_key, 0) >= 3:
            return False
        # 시간 밖 귀가 후보는 버린다. 아침으로 미루지 않는다. 오류는 시간 밖에도 보낸다.
        if not is_error and not (time(9, 0) <= now.time() <= time(21, 30)):
            return False
        day = now.date().isoformat()
        if self.sent_by_day.get(day, 0) >= self.max_per_day:
            return False
        if session_id and session_id in self.sent_sessions:
            return False
        return True

    def mark_sent(self, *, session_id: str | None, now: datetime) -> None:
        day = now.date().isoformat()
        self.sent_by_day[day] = self.sent_by_day.get(day, 0) + 1
        if session_id:
            self.sent_sessions.add(session_id)

    def record_rejection(self, condition_key: str = "homebound") -> None:
        self.rejections[condition_key] = self.rejections.get(condition_key, 0) + 1
