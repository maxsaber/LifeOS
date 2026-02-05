"""
Anomaly detection API endpoints.
"""
from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.services.anomaly_detection import build_anomaly_report

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


class CommunicationAnomalyResponse(BaseModel):
    type: str
    person_id: str
    person_name: str
    days_since_contact: int
    typical_gap_days: int
    gap_multiplier: float
    last_contact: str | None
    circle: int | None


class SentimentAnomalyResponse(BaseModel):
    type: str
    person_id: str
    person_name: str
    average_score: float
    trend: str
    trend_delta: float
    count: int
    window_days: int


class MeetingEventSummaryResponse(BaseModel):
    title: str
    start_time: str
    end_time: str
    duration_hours: float
    source_account: str


class MeetingOverloadAnomalyResponse(BaseModel):
    type: str
    date: str
    total_meeting_hours: float
    threshold_hours: float
    event_count: int
    events: list[MeetingEventSummaryResponse]


class AnomalyReportResponse(BaseModel):
    generated_at: str
    communication: list[CommunicationAnomalyResponse]
    sentiment: list[SentimentAnomalyResponse]
    meeting_overload: list[MeetingOverloadAnomalyResponse]


@router.get("", response_model=AnomalyReportResponse)
async def get_anomaly_report(
    communication_days_back: int = Query(
        default=365,
        ge=30,
        le=3650,
        description="Lookback window for communication patterns",
    ),
    communication_min_interactions: int = Query(
        default=5,
        ge=3,
        le=200,
        description="Minimum interactions to establish a cadence",
    ),
    communication_gap_multiplier: float = Query(
        default=2.0,
        ge=1.1,
        le=10.0,
        description="Gap multiplier vs typical cadence",
    ),
    include_peripheral: bool = Query(
        default=False,
        description="Include peripheral contacts in communication anomalies",
    ),
    sentiment_days: int = Query(
        default=90,
        ge=30,
        le=3650,
        description="Lookback window for sentiment drift",
    ),
    sentiment_min_count: int = Query(
        default=5,
        ge=3,
        le=200,
        description="Minimum sentiment scores to evaluate drift",
    ),
    sentiment_min_delta: float = Query(
        default=-0.1,
        le=0.0,
        ge=-5.0,
        description="Minimum negative trend delta to flag drift",
    ),
    meeting_date: date | None = Query(
        default=None,
        description="Date for meeting overload (YYYY-MM-DD). Defaults to tomorrow",
    ),
    meeting_threshold_hours: float = Query(
        default=8.0,
        ge=1.0,
        le=24.0,
        description="Meeting hours threshold for overload",
    ),
    include_communication: bool = Query(default=True),
    include_sentiment: bool = Query(default=True),
    include_meeting: bool = Query(default=True),
):
    return build_anomaly_report(
        communication_days_back=communication_days_back,
        communication_min_interactions=communication_min_interactions,
        communication_gap_multiplier=communication_gap_multiplier,
        include_peripheral=include_peripheral,
        sentiment_days=sentiment_days,
        sentiment_min_count=sentiment_min_count,
        sentiment_min_delta=sentiment_min_delta,
        meeting_date=meeting_date,
        meeting_threshold_hours=meeting_threshold_hours,
        include_communication=include_communication,
        include_sentiment=include_sentiment,
        include_meeting=include_meeting,
    )
