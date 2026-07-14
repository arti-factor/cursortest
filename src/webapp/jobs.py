"""Einfacher In-Memory-Hintergrund-Job-Runner für lang laufende Vorgänge
(Discovery, Matching, Audit-Läufe) in der Webanwendung.

Bewusst ohne externe Abhängigkeit (kein Celery/Redis) - für ein internes
Agentur-Tool mit überschaubarer paralleler Nutzung reicht ein Thread pro Job.
Jobs leben nur im Prozessspeicher: ein Neustart des Servers verwirft laufende
und abgeschlossene Job-Historie (die eigentlichen Ergebnisse - Standorte,
Reports - sind über clients/<kunde>/ aber bereits persistiert).
"""
from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"  # running | done | error
    result: Any = None
    error: Optional[str] = None
    log: list[str] = field(default_factory=list)
    # Freie Zusatzdaten, die eine Route nach Abschluss braucht (z.B. Client-Slug)
    meta: dict[str, Any] = field(default_factory=dict)

    def append_log(self, message: str) -> None:
        self.log.append(message)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, fn: Callable[[Job], Any], meta: Optional[dict[str, Any]] = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, meta=meta or {})
        with self._lock:
            self._jobs[job.id] = job

        def _runner() -> None:
            try:
                job.result = fn(job)
                job.status = "done"
            except Exception as exc:  # Job-Fehler sollen die Anwendung nie zum Absturz bringen
                job.status = "error"
                job.error = str(exc)
                job.append_log(traceback.format_exc())

        threading.Thread(target=_runner, daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)


jobs = JobManager()
