BEGIN TRANSACTION;
CREATE TABLE control(singleton INTEGER PRIMARY KEY CHECK(singleton=1),payload TEXT NOT NULL);
INSERT INTO "control" VALUES(1,'{"schema": "nasuraya-absence-control/1", "enabled": true, "last_contact_at": "2026-10-16T10:22:23+00:00", "contact_source": "Explicit local operator initialization", "last_claimed_at": "2026-10-17T10:22:23+00:00", "inflight_run_id": null, "last_completed_run_id": "run1"}');
CREATE TABLE local_jobs(
            run_id TEXT PRIMARY KEY REFERENCES runs(id), request_id TEXT UNIQUE NOT NULL,
            digest TEXT NOT NULL, input BLOB NOT NULL, status TEXT NOT NULL,
            result TEXT, resolution TEXT);
INSERT INTO "local_jobs" VALUES('run1','request1','f89ffa253788cd901486af70d75eb536a94e6f23371e0c8bebdd66353332d3e5',X'5B22616263222C2022222C2022D8B3D984D8A7D985225D','abandoned',NULL,'{"evidence":"SIGKILL confirmed and child reaped","now":"2026-10-17T10:22:23Z","operator":"verifier-host","worker_stopped":true}');
CREATE TABLE requests(id TEXT PRIMARY KEY,digest TEXT NOT NULL,receipt TEXT NOT NULL);
INSERT INTO "requests" VALUES('request1','0b1b5125797485a5e11ea6bcbade1e45f71b35704959b225b06807ad93a6924b','{"request_id": "request1", "operation": "claim", "state_after": {"schema": "nasuraya-absence-control/1", "enabled": true, "last_contact_at": "2026-10-16T10:22:23+00:00", "contact_source": "Explicit local operator initialization", "last_claimed_at": "2026-10-17T10:22:23+00:00", "inflight_run_id": "run1", "last_completed_run_id": null}}');
INSERT INTO "requests" VALUES('review','090184a559c479fade99ca4c987400a9e2e314961342fbae29117a43f4bbc781','{"request_id": "review", "operation": "finish", "state_after": {"schema": "nasuraya-absence-control/1", "enabled": true, "last_contact_at": "2026-10-16T10:22:23+00:00", "contact_source": "Explicit local operator initialization", "last_claimed_at": "2026-10-17T10:22:23+00:00", "inflight_run_id": null, "last_completed_run_id": "run1"}}');
CREATE TABLE runs(id TEXT PRIMARY KEY,claimed_at TEXT NOT NULL,finished_at TEXT);
INSERT INTO "runs" VALUES('run1','2026-10-17T10:22:23+00:00','2026-10-17T10:22:23+00:00');
COMMIT;
