"""
Anomaly detection service.

Detects:
- Unusual communication gaps vs. typical cadence
- Sentiment drift in recent interactions
- Meeting overload for a given day
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from api.services.interaction_store import get_interaction_store
from api.services.person_entity import get_person_entity_store
from api.services.sentiment import get_sentiment_store
from api.services.calendar import get_all_events_in_range
from config.settings import settings


@dataclass
class CommunicationAnomaly:
    person_id: str
    person_name: str
    days_since_contact: int
    typical_gap_days: int
    gap_multiplier: float
    last_contact: Optional[datetime]
    circle: Optional[int]

    def to_dict(self) -> dict:
        return {
            "type": "communication_gap",
            "person_id": self.person_id,
            "person_name": self.person_name,
            "days_since_contact": self.days_since_contact,
            "typical_gap_days": self.typical_gap_days,
            "gap_multiplier": self.gap_multiplier,
            "last_contact": self.last_contact.isoformat() if self.last_contact else None,
            "circle": self.circle,
        }


@dataclass
class SentimentAnomaly:
    person_id: str
    person_name: str
    average_score: float
    trend: str
    trend_delta: float
    count: int
    window_days: int

    def to_dict(self) -> dict:
        return {
            "type": "sentiment_drift",
            "person_id": self.person_id,
            "person_name": self.person_name,
            "average_score": self.average_score,
            "trend": self.trend,
            "trend_delta": self.trend_delta,
            "count": self.count,
            "window_days": self.window_days,
        }


@dataclass
class MeetingEventSummary:
    title: str
    start_time: datetime
    end_time: datetime
    duration_hours: float
    source_account: str

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_hours": round(self.duration_hours, 2),
            "source_account": self.source_account,
        }


@dataclass
class MeetingOverloadAnomaly:
    date: date
    total_meeting_hours: float
    threshold_hours: float
    event_count: int
    events: list[MeetingEventSummary]

    def to_dict(self) -> dict:
        return {
            "type": "meeting_overload",
            "date": self.date.isoformat(),
            "total_meeting_hours": round(self.total_meeting_hours, 2),
            "threshold_hours": self.threshold_hours,
            "event_count": self.event_count,
            "events": [e.to_dict() for e in self.events],
        }


_MIN_GAP_BY_CIRCLE = {
    0: 3,
    1: 5,
    2: 7,
    3: 14,
    4: 21,
    5: 30,
    6: 45,
    7: 60,
}


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _median(values: list[int]) -> Optional[int]:
    if not values:
        return None
    values_sorted = sorted(values)
    return values_sorted[len(values_sorted) // 2]


def get_communication_anomalies(
    days_back: int = 365,
    min_interactions: int = 5,
    gap_multiplier: float = 2.0,
    include_peripheral: bool = False,
) -> list[CommunicationAnomaly]:
    person_store = get_person_entity_store()
    interaction_store = get_interaction_store()

    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days_back)

    all_people = person_store.get_all()
    person_lookup = {p.id: p for p in all_people}

    hidden_person_ids = {
        p.id for p in person_store.get_all(include_hidden=True) if p.hidden
    }

    exclude_ids = {settings.my_person_id} if settings.my_person_id else set()
    exclude_ids.update(hidden_person_ids)

    if not include_peripheral:
        peripheral_ids = {p.id for p in all_people if p.is_peripheral_contact}
        exclude_ids.update(peripheral_ids)

    interactions = interaction_store.get_all_in_range(
        start_date=start_date,
        end_date=now,
        exclude_person_ids=list(exclude_ids),
    )

    by_person: dict[str, list[datetime]] = {}
    for interaction in interactions:
        if interaction.person_id not in person_lookup:
            continue
        ts = _ensure_aware(interaction.timestamp)
        by_person.setdefault(interaction.person_id, []).append(ts)

    anomalies: list[CommunicationAnomaly] = []

    for person_id, dates in by_person.items():
        if len(dates) < min_interactions:
            continue
        dates_sorted = sorted(dates)
        gaps = [
            max(0, (dates_sorted[i + 1] - dates_sorted[i]).days)
            for i in range(len(dates_sorted) - 1)
        ]
        typical_gap = _median(gaps)
        if typical_gap is None:
            continue

        person = person_lookup[person_id]
        circle = person.dunbar_circle if person.dunbar_circle is not None else 7
        min_gap = _MIN_GAP_BY_CIRCLE.get(circle, 30)
        if typical_gap < min_gap:
            typical_gap = min_gap

        last_contact = dates_sorted[-1]
        days_since = (now - last_contact).days

        if days_since > typical_gap * gap_multiplier:
            anomalies.append(
                CommunicationAnomaly(
                    person_id=person_id,
                    person_name=person.display_name or person.canonical_name,
                    days_since_contact=days_since,
                    typical_gap_days=typical_gap,
                    gap_multiplier=gap_multiplier,
                    last_contact=last_contact,
                    circle=circle,
                )
            )

    anomalies.sort(
        key=lambda a: (a.circle if a.circle is not None else 99, -(a.days_since_contact / max(a.typical_gap_days, 1)))
    )
    return anomalies


def get_sentiment_drift_anomalies(
    days: int = 90,
    min_count: int = 5,
    min_delta: float = -0.1,
) -> list[SentimentAnomaly]:
    sentiment_store = get_sentiment_store()
    person_store = get_person_entity_store()

    people = person_store.get_all()
    anomalies: list[SentimentAnomaly] = []

    for person in people:
        trend_data = sentiment_store.get_trend(person.id, days=days)
        count = trend_data.get("count", 0)
        if count < min_count:
            continue
        trend = trend_data.get("trend", "stable")
        trend_delta = trend_data.get("trend_delta", 0.0)
        average = trend_data.get("average", 0.0)

        if trend == "declining" and trend_delta <= min_delta:
            anomalies.append(
                SentimentAnomaly(
                    person_id=person.id,
                    person_name=person.display_name or person.canonical_name,
                    average_score=average,
                    trend=trend,
                    trend_delta=trend_delta,
                    count=count,
                    window_days=days,
                )
            )

    anomalies.sort(key=lambda a: a.trend_delta)
    return anomalies


def get_meeting_overload_anomaly(
    target_date: Optional[date] = None,
    threshold_hours: float = 8.0,
) -> Optional[MeetingOverloadAnomaly]:
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    now_local = datetime.now(local_tz)

    if target_date is None:
        target_date = (now_local + timedelta(days=1)).date()

    start_dt = datetime.combine(target_date, time.min, tzinfo=local_tz)
    end_dt = datetime.combine(target_date, time.max, tzinfo=local_tz)

    events = get_all_events_in_range(start_dt, end_dt)

    total_hours = 0.0
    summaries: list[MeetingEventSummary] = []

    for event in events:
        if getattr(event, "is_all_day", False):
            continue
        start = event.start_time
        end = event.end_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=local_tz)
        if end.tzinfo is None:
            end = end.replace(tzinfo=local_tz)
        duration_hours = max(0.0, (end - start).total_seconds() / 3600)
        if duration_hours == 0:
            continue
        total_hours += duration_hours
        summaries.append(
            MeetingEventSummary(
                title=event.title,
                start_time=start,
                end_time=end,
                duration_hours=duration_hours,
                source_account=getattr(event, "source_account", "unknown"),
            )
        )

    if total_hours < threshold_hours:
        return None

    return MeetingOverloadAnomaly(
        date=target_date,
        total_meeting_hours=total_hours,
        threshold_hours=threshold_hours,
        event_count=len(summaries),
        events=summaries,
    )


def build_anomaly_report(
    communication_days_back: int = 365,
    communication_min_interactions: int = 5,
    communication_gap_multiplier: float = 2.0,
    include_peripheral: bool = False,
    sentiment_days: int = 90,
    sentiment_min_count: int = 5,
    sentiment_min_delta: float = -0.1,
    meeting_date: Optional[date] = None,
    meeting_threshold_hours: float = 8.0,
    include_communication: bool = True,
    include_sentiment: bool = True,
    include_meeting: bool = True,
) -> dict:
    communication = []
    sentiment = []
    meeting_overload = []

    if include_communication:
        communication = [
            a.to_dict()
            for a in get_communication_anomalies(
                days_back=communication_days_back,
                min_interactions=communication_min_interactions,
                gap_multiplier=communication_gap_multiplier,
                include_peripheral=include_peripheral,
            )
        ]

    if include_sentiment:
        sentiment = [
            a.to_dict()
            for a in get_sentiment_drift_anomalies(
                days=sentiment_days,
                min_count=sentiment_min_count,
                min_delta=sentiment_min_delta,
            )
        ]

    if include_meeting:
        overload = get_meeting_overload_anomaly(
            target_date=meeting_date,
            threshold_hours=meeting_threshold_hours,
        )
        if overload:
            meeting_overload = [overload.to_dict()]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "communication": communication,
        "sentiment": sentiment,
        "meeting_overload": meeting_overload,
    }
