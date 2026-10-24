BEGIN TRANSACTION;
CREATE TABLE control(singleton INTEGER PRIMARY KEY CHECK(singleton=1),payload TEXT NOT NULL);
INSERT INTO "control" VALUES(1,'{"schema": "nasuraya-absence-control/1", "enabled": true, "last_contact_at": "2026-10-16T10:22:23+00:00", "contact_source": "Explicit local operator initialization", "last_claimed_at": "2026-10-17T10:22:23+00:00", "inflight_run_id": null, "last_completed_run_id": "run1"}');
CREATE TABLE local_jobs(
            run_id TEXT PRIMARY KEY REFERENCES runs(id), request_id TEXT UNIQUE NOT NULL,
            digest TEXT NOT NULL, input BLOB NOT NULL, status TEXT NOT NULL,
            result TEXT, resolution TEXT);
INSERT INTO "local_jobs" VALUES('run1','request1','f89ffa253788cd901486af70d75eb536a94e6f23371e0c8bebdd66353332d3e5',X'5B22616263222C2022222C2022D8B3D984D8A7D985225D','completed','{"input_bytes":23,"input_sha256":"554547e836a933725b741c12c0f07813dd5cf4ca8659d48e418ec1619e4e4b91","record_count":3,"record_sha256":["ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad","e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","bda1fa48345336618741fd2c4bc02809eb099c49a9b02fb5056401ab6d4dc3e6"],"schema":"nasuraya-local-integrity/1","utf8_bytes":11}',NULL);
CREATE TABLE requests(id TEXT PRIMARY KEY,digest TEXT NOT NULL,receipt TEXT NOT NULL);
INSERT INTO "requests" VALUES('request1','0b1b5125797485a5e11ea6bcbade1e45f71b35704959b225b06807ad93a6924b','{"request_id": "request1", "operation": "claim", "state_after": {"schema": "nasuraya-absence-control/1", "enabled": true, "last_contact_at": "2026-10-16T10:22:23+00:00", "contact_source": "Explicit local operator initialization", "last_claimed_at": "2026-10-17T10:22:23+00:00", "inflight_run_id": "run1", "last_completed_run_id": null}}');
INSERT INTO "requests" VALUES('local-finish-34e9aedefffddf04c3cf3f9e055ba714e9ebe21b828e6170eeb7b610123d9f7d','090184a559c479fade99ca4c987400a9e2e314961342fbae29117a43f4bbc781','{"request_id": "local-finish-34e9aedefffddf04c3cf3f9e055ba714e9ebe21b828e6170eeb7b610123d9f7d", "operation": "finish", "state_after": {"schema": "nasuraya-absence-control/1", "enabled": true, "last_contact_at": "2026-10-16T10:22:23+00:00", "contact_source": "Explicit local operator initialization", "last_claimed_at": "2026-10-17T10:22:23+00:00", "inflight_run_id": null, "last_completed_run_id": "run1"}}');
CREATE TABLE runs(id TEXT PRIMARY KEY,claimed_at TEXT NOT NULL,finished_at TEXT);
INSERT INTO "runs" VALUES('run1','2026-10-17T10:22:23+00:00','2026-10-17T10:22:23+00:00');
COMMIT;
