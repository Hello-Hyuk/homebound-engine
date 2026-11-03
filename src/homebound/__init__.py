"""GPS 궤적 귀가 판정 공용 엔진.

v3 명세의 핵심만 구현한다. 자동 제어를 하지 않고, 제안 후보와 근거만 만든다.
원시 좌표는 이 패키지 밖으로 보내지 않는다. 제안에는 거리 변화, 방향,
도착 예상 시간, 머무름 시간 같은 요약만 들어간다.
"""

from .engine import (
    CompanionStatus,
    Engine,
    EngineConfig,
    EngineResult,
    Event,
    Grade,
    ProposalPolicy,
    State,
    haversine_m,
    quality_weight,
)
from .learning import (
    AgentSummary,
    LearnedRoute,
    StaySegment,
    agent_summary,
    detect_stays,
    route_match,
)

__all__ = [
    "CompanionStatus",
    "Engine",
    "EngineConfig",
    "EngineResult",
    "Event",
    "Grade",
    "ProposalPolicy",
    "State",
    "haversine_m",
    "quality_weight",
    "AgentSummary",
    "LearnedRoute",
    "StaySegment",
    "agent_summary",
    "detect_stays",
    "route_match",
]

__version__ = "0.1.0"
