# Nasuraya / Tadash — isolated agent loop

Synthetic workshop only. No body simulation or Decision Core integration.

Backend: `agents_api`; status: `api_error`; mutations: 0.

## Host measurements

```json
{
  "backend": "agents_api",
  "status": "api_error",
  "initial_state": {
    "energy": 45,
    "heat": 50,
    "pending_jobs": 3,
    "completed_jobs": 0,
    "tick": 0
  },
  "final_state": {
    "energy": 45,
    "heat": 50,
    "pending_jobs": 3,
    "completed_jobs": 0,
    "tick": 0
  },
  "evaluation": {
    "goal_reached": false,
    "safe": true,
    "pending_jobs": 3,
    "completed_jobs": 0
  },
  "actions_used": 0,
  "event_count": 10,
  "live_api_verified": false,
  "api_transport": "live_sdk",
  "session_id": "sess_0a65c91ebf075b54006acd79d846cc8193800c6c88eec83b70",
  "cleanup_status": "failed"
}
```

## Event index

| Seq | Event | Detail |
| --- | --- | --- |
| 1 | run_started |  |
| 2 | api_session_created |  |
| 3 | api_event |  |
| 4 | api_event |  |
| 5 | api_event |  |
| 6 | api_event |  |
| 7 | api_event |  |
| 8 | api_error |  |
| 9 | api_cleanup_failed |  |
| 10 | run_finished | api_error |

The JSONL trace records observations, validated calls, state changes and evaluations.
Selection source and API verification scope are recorded in the summary.
SDK tests with controlled responses do not establish live OpenAI service access or model performance.
This run does not demonstrate a continuous background process, physical embodiment or persistent learning.
