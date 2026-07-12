"""Turns alerts into incidents, correlates related alerts (same time window) into one
incident with a timeline, drives state transitions, and persists incidents to SQLite.
"""

import sqlite3
import uuid
from datetime import datetime

from config import settings
from schemas.models import Alert, DetectionResult, Incident
from soc.state_machine import transition

_SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
_SEVERITY_BY_CLASSIFICATION = {"SUSPICIOUS": "MEDIUM", "HIGH_RISK": "HIGH", "CRITICAL": "CRITICAL"}
_TERMINAL_STATUSES = ("RESOLVED", "FALSE_POSITIVE")


def _timeline_event(timestamp: datetime, kind: str, **detail) -> dict:
    return {"timestamp": timestamp.isoformat(), "type": kind, **detail}


def _evidence_entry(alert: Alert) -> dict:
    return {"sensor_id": alert.sensor_id, "asset_id": alert.asset_id, "detection": alert.detection.model_dump(mode="json")}


class IncidentManager:
    def __init__(self, db_path: str = settings.DB_PATH) -> None:
        self._db = sqlite3.connect(db_path)
        self._db.execute("CREATE TABLE IF NOT EXISTS incidents (incident_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self._db.commit()
        self._open: dict[str, Incident] = {}
        self._last_alert_at: dict[str, datetime] = {}
        self._restore_open_incidents()

    def _restore_open_incidents(self) -> None:
        """On startup, non-terminal incidents from a prior run become open again, with
        their last-alert time taken from the most recent timeline entry, so a restart
        doesn't fork an in-progress incident into a duplicate.
        """
        for (data,) in self._db.execute("SELECT data FROM incidents"):
            incident = Incident.model_validate_json(data)
            if incident.status in _TERMINAL_STATUSES:
                continue
            self._open[incident.incident_id] = incident
            self._last_alert_at[incident.incident_id] = datetime.fromisoformat(incident.timeline[-1]["timestamp"])

    def handle_detection(self, sensor_id: str, asset_id: str, detection: DetectionResult) -> Incident | None:
        """Wraps a workflow-triggering DetectionResult in an Alert and files it. Returns
        None when the detection doesn't cross the workflow threshold - nothing to file.
        """
        if not detection.trigger_soc_workflow:
            return None
        alert = Alert(
            alert_id=str(uuid.uuid4()),
            event_id=detection.event_id,
            sensor_id=sensor_id,
            asset_id=asset_id,
            severity=_SEVERITY_BY_CLASSIFICATION.get(detection.classification, "MEDIUM"),
            classification=detection.classification,
            created_at=datetime.now(),
            detection=detection,
        )
        return self._file(alert)

    def _file(self, alert: Alert) -> Incident:
        incident = self._find_correlatable(alert)
        if incident is None:
            incident = self._create(alert)
        else:
            self._correlate(incident, alert)
        self._last_alert_at[incident.incident_id] = alert.created_at
        self._persist(incident)
        return incident

    def _find_correlatable(self, alert: Alert) -> Incident | None:
        for incident in self._open.values():
            last_seen = self._last_alert_at.get(incident.incident_id)
            if last_seen and 0 <= (alert.created_at - last_seen).total_seconds() <= settings.CORRELATION_WINDOW_SECONDS:
                return incident
        return None

    def _create(self, alert: Alert) -> Incident:
        incident = Incident(
            incident_id=str(uuid.uuid4()),
            status="NEW",
            severity=alert.severity,
            created_at=alert.created_at,
            correlated_alert_ids=[alert.alert_id],
            affected_assets=[alert.asset_id],
            timeline=[_timeline_event(alert.created_at, "INCIDENT_CREATED", alert_id=alert.alert_id, asset_id=alert.asset_id)],
            probable_attack=None,
            evidence_package={alert.alert_id: _evidence_entry(alert)},
            response_actions=[],
        )
        self._open[incident.incident_id] = incident
        return incident

    def _correlate(self, incident: Incident, alert: Alert) -> None:
        incident.correlated_alert_ids.append(alert.alert_id)
        if alert.asset_id not in incident.affected_assets:
            incident.affected_assets.append(alert.asset_id)
        if _SEVERITY_ORDER.index(alert.severity) > _SEVERITY_ORDER.index(incident.severity):
            incident.severity = alert.severity
        incident.evidence_package[alert.alert_id] = _evidence_entry(alert)
        incident.timeline.append(_timeline_event(alert.created_at, "ALERT_CORRELATED", alert_id=alert.alert_id, asset_id=alert.asset_id))

    def advance(self, incident: Incident, target_status: str, note: str = "") -> Incident:
        """Mutates and returns `incident`. Callers should pass the instance from
        handle_detection/get, not a separately-reconstructed copy - `_open` is
        re-pointed at this exact object either way, so a stale copy elsewhere
        (e.g. a second get() call) is superseded rather than silently reverting it.
        """
        incident.status = transition(incident.status, target_status)
        incident.timeline.append(_timeline_event(datetime.now(), "STATE_CHANGE", status=target_status, note=note))
        if incident.status in _TERMINAL_STATUSES:
            self._open.pop(incident.incident_id, None)
        else:
            self._open[incident.incident_id] = incident
        self._persist(incident)
        return incident

    def _persist(self, incident: Incident) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO incidents (incident_id, data) VALUES (?, ?)",
            (incident.incident_id, incident.model_dump_json()),
        )
        self._db.commit()

    def get(self, incident_id: str) -> Incident | None:
        row = self._db.execute("SELECT data FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        return Incident.model_validate_json(row[0]) if row else None

    def save(self, incident: Incident) -> None:
        """Persists field changes made directly on an incident object (e.g. an agent
        setting probable_attack or response_actions) outside of a state transition.
        """
        self._persist(incident)

    def close(self) -> None:
        self._db.close()
